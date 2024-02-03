#
# KAT500 & KAT-500 Remote client data
#
__author__ = 'J. B. Otterson'
__copyright__ = """
Copyright 2022, J. B. Otterson N1KDO.
Redistribution and use in source and binary forms, with or without modification, 
are permitted provided that the following conditions are met:
  1. Redistributions of source code must retain the above copyright notice, 
     this list of conditions and the following disclaimer.
  2. Redistributions in binary form must reproduce the above copyright notice, 
     this list of conditions and the following disclaimer in the documentation 
     and/or other materials provided with the distribution.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND 
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, 
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE 
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
OF THE POSSIBILITY OF SUCH DAMAGE.
"""
__version__ = '0.9.0'

# disable pylint import error
# pylint: disable=E0401

import gc

from kdevice import KDevice, ClientData, BufferAndLength
from utils import upython, milliseconds, safe_int

if upython:
    import uasyncio as asyncio
    import micro_logging as logging
    from uasyncio import TimeoutError
else:
    import asyncio
    import logging
    from asyncio.exceptions import TimeoutError


class KAT500(KDevice):
    antenna_number_to_name = ('One', 'Two', 'Three')
    band_number_to_name = ('160m', '80m', '60m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m')
    mode_name_dict = {'M': 'Manual', 'A': 'Auto', 'B': 'Bypass'}
    # noinspection SpellCheckingInspection
    key_names = (
        b'tuner::button::AMPI',       # 00: '0' or '1'
        b'tuner::button::ATTN',       # 01: '0' or '1'
        b'tuner::button::BYP',        # 02: '0' or '1'
        b'tuner::button::Clear',      # 03: '0'
        b'tuner::button::Power',      # 04: '1'
        b'tuner::button::Tune',       # 05: '0'
        b'tuner::dropdown::Antenna',  # 06: 'Three'
        b'tuner::dropdown::Band',     # 07: '10m'
        b'tuner::dropdown::Mode',     # 08: 'Manual'
        b'tuner::fault',              # 09: '0'
        b'tuner::meter::Frequency',   # 10: '28075'
        b'tuner::meter::VFWD',        # 11: '2'
        b'tuner::meter::VRFL',        # 12: '2'
        b'tuner::meter::VSWR',        # 13: '1.18'
        b'tuner::meter::VSWRB',       # 14: '1.65'
    )

    fault_texts = ('NO FAULT',                   # 0
                   'NO MATCH',                   # 1
                   'POWER ABOVE DESIGN LIMIT',   # 2
                   'POWER ABOVE RELAY LIMIT',    # 3
                   'SWR ABOVE THRESHOLD',        # 4
                   'NO TUNER',                   # 5 n1kdo extension
                   'POWERING UP',                # 6 n1kdo extension
                   )

    initial_queries = (b';',       # attention!
                       b'I;',      # identify device; returns KAT500
                       b'RV;',     # Firmware Revision
                       b'SN;',     # Serial Number
                       b'PS;',     # Power on/off
                       )

    normal_queries = (b'VFWD;',   # Forward ADC count
                      b'BYP;',    # bypass
                      b'AMPI;',   # amp interrupt key line
                      b'VRFL;',   # reverse ADC count
                      b'ATTN;',   # attenuator
                      b'VSWR;',   # VSWR
                      b'AN;',     # antenna select
                      b'VSWRB;',  # bypass VSWR
                      b'MD;',     # mode
                      b'VFWD;',   # forward ADC count
                      b'F;',      # frequency
                      b'VRFL;',   # reverse ADC count
                      b'TP;',     # tune poll
                      b'BN;',     # band number
                      b'FLT;',    # fault display
                      b'PS;',     # power switch
                      )

    def __init__(self, username=None, password=None, port_name=None):
        super().__init__(username, password, port_name, len(self.key_names))

        self.device_data[4] = '1'
        self.device_data[6] = ''
        self.device_data[7] = ''
        self.device_data[7] = ''
        self.device_data[13] = '1.0'
        self.device_data[14] = '1.0'

    def band_label_to_number(self, label):
        for i, band_name in enumerate(self.band_number_to_name):
            if label == band_name:
                return i
        return None

    def get_fault_text(self, fault_code):
        if fault_code.isdigit():
            fault_num = int(fault_code)
            if fault_num < len(self.fault_texts):
                return self.fault_texts[fault_num]
        return fault_code

    def process_kat500_message(self, msg):
        if msg is None or len(msg) == 0:
            logging.warning('empty message', 'kat500:process_kat500_message')
        if msg == ';':
            return
        if msg[-1] != ';':
            logging.warning(f'bad data: {msg}' 'kat500:process_kat500_message')
            return
        lm = len(msg)
        if lm >= 7:  # check for 6 letter message names
            fragment = msg[0:6]
            if fragment == 'KAT500':
                return  # just eat this.
        if lm >= 6:  # check for 5 letter message names
            fragment = msg[0:5]
            if fragment == 'VSWRB':
                data = msg[5:-1].strip()
                if data is not None:
                    self.update_device_data(14, data)
                return
        if lm >= 5:  # check for 4 letter message names. AMPI ATTN VFWD VRFL VSWR
            fragment = msg[0:4]
            if lm > 5:
                data = msg[4:-1].strip()
            else:
                data = None
            if fragment == 'AMPI':
                if data is not None:
                    self.update_device_data(0, data)
                return
            if fragment == 'ATTN':
                if data is not None:
                    self.update_device_data(1, data)
                return
            if fragment == 'VFWD':
                if data is not None:
                    self.update_device_data(11, data)
                return
            if fragment == 'VRFL':
                if data is not None:
                    self.update_device_data(12, data)
                return
            if fragment == 'VSWR':
                if data is not None:
                    self.update_device_data(13, data)
                return
        if lm >= 4:  # check for 3 letter message names. BYP FLT
            fragment = msg[0:3]
            if lm > 4:
                data = msg[3:-1]
            else:
                data = None
            if fragment == 'BYP':
                if data is not None:
                    self.update_device_data(2, data)
                return
            if fragment == 'FLT':
                if data is not None:
                    self.update_device_data(9, data)
                return
        if lm >= 3:  # check for 2 letter message names. AN BN MD PS RV SL SN TP
            fragment = msg[0:2]
            # logging.warning(f'fragment "{fragment}"', 'kat500:process_kat500_message')
            if lm > 3:
                data = msg[2:-1]
            else:
                data = None
            if fragment == 'AN':
                if data is not None:
                    antenna_number = safe_int(data)
                    antenna = self.antenna_number_to_name[antenna_number - 1]
                    self.update_device_data(6, antenna)
                return
            if fragment == 'BN':
                if data is not None:
                    band_number = safe_int(data)
                    band_name = self.band_number_to_name[band_number]
                    self.update_device_data(7, band_name)
                return
            if fragment == 'MD':
                if data is not None:
                    mode_name = self.mode_name_dict.get(data) or data
                    self.update_device_data(8, mode_name)
                return
            if fragment == 'PS':
                if data is not None:
                    self.update_device_data(4, data)
                return
            if fragment == 'RV':
                if data is None:
                    logging.info('Revision Query', 'kat500:process_kat500_message')
                else:
                    logging.info(f'Revision {data}', 'kat500:process_kat500_message')
                return
            if fragment == 'SL':
                if data is None:
                    logging.info('SLeep Query', 'kat500:process_kat500_message')
                else:
                    logging.info(f'SLeep query {data}', 'kat500:process_kat500_message')
                return
            if fragment == 'SN':
                if data is None:
                    logging.info('Serial Number Query', 'kat500:process_kat500_message')
                else:
                    logging.info(f'Serial Number {data}', 'kat500:process_kat500_message')
                return
            if fragment == 'TP':
                if data is not None:
                    self.update_device_data(5, data)  # update tuning status
                return
        if lm >= 2:  # check for 1 letter message names. F
            fragment = msg[0:1]
            # logging.warning(f'fragment "{fragment}"', 'kat500:process_kat500_message')
            if lm > 1:
                data = msg[2:-1]
            else:
                data = None
            if fragment == 'F':
                if data is not None:
                    self.update_device_data(10, data)
                return
        logging.error(f'unhandled: {msg} len {lm}', 'kat500:process_kat500_message')

    def set_tuner_off_data(self):
        # reset all the indicators when the amp is turned off.
        self.update_device_data(4, '0')  # set POWER to not powered
        self.update_device_data(9, '0')  # set FAULT to not faulted

    # KAT500 tuner polling code
    async def kat500_server(self):
        """
        this manages the connection to the physical tuner
        :return: None
        """

        tuner_state = 0  # 0 not connected, 1 online state unknown , 2 power off, 3 power on
        bl = BufferAndLength(bytearray(16))
        next_command = 0
        run_loop = True

        while run_loop:
            if tuner_state == 0:  # unknown / no response state
                # poke at the tuner -- is it connected?
                await self.device_send_receive(b';', bl)
                # connected will return a ';' here
                if bl.bytes_received != 1 or bl.buffer[0] != 59:
                    self.update_device_data(9, '5')
                else:
                    tuner_state = 1
                    logging.info('tuner state 0-->1', 'kat500:kat500_server')
            elif tuner_state == 1:  # apparently connected
                # ask if it is turned on.
                await self.device_send_receive(b'PS;', bl)  # power up.
                # is b'PS1;' when tuner is on.
                # is b'PS0;' when tuner is off
                # is b'' when tuner is not found.
                if bl.bytes_received == 0:
                    tuner_state = 0
                    self.update_device_data(4, '0')  # set POWER to not powered
                    self.update_device_data(9, '5')  # set FAULT to NO TUNER
                    logging.info('1: no response, amp state 1-->0', 'kat500:kat500_server')
                elif bl.bytes_received == 4 and bl.buffer[2] == 49:  # '1', tuner appears on
                    tuner_state = 3  # tuner is powered on.
                    self.update_device_data(4, '1')  # set POWER to POWERED
                    self.update_device_data(9, '0')  # set FAULT to no fault
                    self.enqueue_command(self.initial_queries)
                    logging.info('tuner state 1-->3', 'kat500:kat500_server')
                elif bl.bytes_received == 4 and bl.buffer[2] == 48:  # '0', tuner connected but off.
                    tuner_state = 2
                    self.update_device_data(4, '0')  # set POWER to not powered
                    self.update_device_data(9, '0')  # set FAULT to no fault
                    logging.info('tuner state 1-->2', 'kat500:kat500_server')
                else:
                        logging.warning(f'1: unexpected data {bl.buffer[:bl.bytes_received]}', 'kat500:kat500_server')
            elif tuner_state == 2:  # connected, power off.
                query = self.dequeue_command()
                # throw away any queries except the ON command.
                if query is not None and query == b'PS1;':  # turn on tuner
                    await self.device_send_receive(b'PS1', bl)
                    self.update_device_data(9, '6')  # set FAULT to powering up
                    await asyncio.sleep(1.50)
                    tuner_state = 0  # test state again.
                    logging.info('tuner state 2-->0', 'kat500:kat500_server')
                else:
                    await self.device_send_receive(b'PS1;', bl, wait_time=1.5)  # hi there.
                    # is b'PS1;' when tuner is on.
                    # is b'PS0;' when tuner is off
                    # is b'' when tuner is not found.
                    if bl.bytes_received == 0:
                        tuner_state = 1
                        self.update_device_data(4, '0')  # set POWER to not powered
                        self.update_device_data(9, '5')  # set FAULT to not found
                        logging.info('no data, tuner state 2-->1', 'kat500:kat500_server')
                    elif bl.bytes_received == 4 and bl.buffer[2] == 49:  # '1', tuner appears on
                        tuner_state = 3  # tuner is powered on.
                        self.update_device_data(4, '1')  # set POWER to powered on
                        self.update_device_data(9, '0')  # set FAULT to no fault
                        self.enqueue_command(self.initial_queries)
                        logging.info('tuner state 2-->3', 'kat500:kat500_server')
                    elif bl.bytes_received == 4 and bl.buffer[2] == 48:  # '0', tuner connected but off.
                        pass  # this is the expected result when tuner is off
                    else:
                        logging.info(f'2: unexpected data {bl.buffer[:bl.bytes_received]}', 'kat500:kat500_server')
            elif tuner_state == 3:  # connected, power on.
                query = self.dequeue_command()
                if query is None:
                    query = self.normal_queries[next_command]
                    if next_command == len(self.normal_queries) - 1:  # this is the last one
                        next_command = 0
                    else:
                        next_command += 1

                # timeout = 2.0 if query in (b'MDA;', b'MDB;', b'MDM;') else 0.05
                await self.device_send_receive(query, bl, retries=2)
                if query == b'PS0;':
                    tuner_state = 1
                    logging.info('power off command, tuner state 3-->1', 'kat500:kat500_server')
                    self.update_device_data(4, '0')  # set POWER to not powered
                    self.update_device_data(9, '0')  # set FAULT  to no fault
                    self.set_tuner_off_data()
                    await asyncio.sleep(1.50)
                else:
                    if bl.bytes_received > 0:
                        self.process_kat500_message(bl.data().decode())
                    else:
                        tuner_state = 0
                        self.update_device_data(9, '5')  # set FAULT to NO TUNER
                        self.set_tuner_off_data()
                        logging.info(f'no response to command {query}, tuner state 3-->0', 'kat500:kat500_server')
            else:
                logging.error(f'invalid tuner state: {tuner_state}, bye bye.', 'kat500:kat500_server')
                run_loop = False

            await asyncio.sleep(0.025)  # 40/sec

    async def serve_kat500_remote_client(self, reader, writer, verbosity=3):
        """
        this provides KAT500-Remote compatible control.
        """
        # verbosity = 4  # 1 is error, 2 is warn, 3 is info, 4 is debug, 5 is trace, or something like that.
        t0 = milliseconds()
        extra = writer.get_extra_info('peername')
        client_name = f'{extra[0]}:{extra[1]}'
        client_data = ClientData(client_name)
        client_data.update_list.extend((9, 4, 5, 0, 1, 2, 3, 6, 8, 7, 13, 14, 11, 12, 10))  # items to send.
        self.network_clients.append(client_data)
        logging.info(f'client {client_name} connected', 'kat500:serve_kat500_remote_client')

        try:
            while client_data.connected:
                try:
                    message = await asyncio.wait_for(self.read_network_client(reader), 0.05)
                    timed_out = False
                except TimeoutError:
                    message = None
                    timed_out = True
                if message is not None and not timed_out:
                    client_data.last_activity = milliseconds()
                    if len(message) > 0:
                        logging.debug(f'RECEIVED "{message}" FROM client {client_name}',
                                      'kat500:serve_kat500_remote_client')
                    if len(message) == 0:  # keepalive?
                        logging.debug(f'RECEIVED keepalive FROM client {client_name}',
                                      'kat500:serve_kat500_remote_client')
                    elif message.startswith('server::login::'):
                        up_list = message[15:].split('::')
                        if up_list[0] != self.username:
                            response = b'server::login::invalid::Invalid username provided. ' \
                                       b'Remote control will not be allowed.\n'
                        elif up_list[1] != self.password:
                            response = b'server::login::invalid::Invalid password provided. ' \
                                       b'Remote control will not be allowed.\n'
                        else:
                            response = b'server::login::valid\n'
                            client_data.authorized = True
                        writer.write(response)
                        client_data.last_activity = milliseconds()
                        logging.debug(f'sending "{response.decode().strip()}"', 'kat500:serve_kat500_remote_client')
                    else:
                        if client_data.authorized:
                            if message.startswith('tuner::button::clear::'):
                                self.enqueue_command(b'FLTC;')
                            elif message.startswith('tuner::dropdown::Mode::'):
                                value = message[23:]
                                command = None
                                if value == 'Bypass':
                                    command = b'MDB;MD;'
                                elif value == 'Auto':
                                    command = b'MDA;MD;'
                                elif value == 'Manual':
                                    command = b'MDM;MD;'
                                self.enqueue_command(command)
                            elif message.startswith('tuner::dropdown::Antenna::'):
                                value = message[26:]
                                command = None
                                if value == 'One':
                                    command = b'AN1;AN;'
                                elif value == 'Two':
                                    command = b'AN2;AN;'
                                elif value == 'Three':
                                    command = b'AN3;AN;'
                                else:
                                    logging.error(f'confused; antenna dropdown value {value}',
                                                  'kat500:serve_kat500_remote_client')
                                if command is not None:
                                    self.enqueue_command(command)
                            elif message.startswith('tuner::button::AMPI::'):
                                value = message[21:]
                                if value == '1':
                                    command = b'AMPI1;AMPI;'
                                else:
                                    command = b'AMPI0;AMPI;'
                                self.enqueue_command(command)
                            elif message.startswith('tuner::button::ATTN::'):
                                value = message[21:]
                                if value == '1':
                                    command = b'ATTN1;ATTN;'
                                else:
                                    command = b'ATTN0;ATTN;'
                                self.enqueue_command(command)
                            elif message.startswith('tuner::button::BYP::'):
                                value = message[20:]
                                if value == '1':
                                    command = b'BYPB;BYP;'
                                else:
                                    command = b'BYPN;BYP;'
                                self.enqueue_command(command)
                            elif message.startswith('tuner::button::Power::'):
                                value = message[22:]
                                if value == '1':
                                    command = b'PS1;PS;'
                                else:
                                    command = b'PS0;PS;'
                                self.enqueue_command(command)
                            elif message.startswith('tuner::button::Tune::'):
                                value = message[21:]
                                if value == '1':
                                    command = b'FT;TP;'
                                    self.enqueue_command(command)
                            else:
                                logging.info(f'unhandled message from client "{message}"',
                                             'kat500:serve_kat500_remote_client')
                else:  # response was None
                    if not timed_out:
                        logging.info(f'client {client_data} response was None, setting connected=false',
                                     'kat500:serve_kat500_remote_client')
                        client_data.connected = False

                # send any outstanding data back...
                if len(client_data.update_list) > 0:
                    index = client_data.update_list.pop(0)
                    writer.write(self.key_names[index])
                    payload = f'::{self.device_data[index]}\n'.encode()
                    writer.write(payload)
                    await writer.drain()
                    client_data.last_activity = milliseconds()
                    logging.debug(f'sent "{self.key_names[index].decode()}{payload.decode().strip()}"',
                                  'kat500:serve_kat500_remote_client')

                since_last_activity = milliseconds() - client_data.last_activity
                if since_last_activity > 15000:
                    writer.write(b'\n')
                    await writer.drain()
                    client_data.last_activity = milliseconds()
                    logging.debug(f'SENT keepalive TO client {client_name}', 'kat500:serve_kat500_remote_client')
                gc.collect()

            # connection closing
            logging.info(f'client {client_name} connection closing...', 'kat500:serve_kat500_remote_client')
            writer.close()
            await writer.wait_closed()
        except ConnectionAbortedError as ex:
            logging.warning(f'client {client_name} connection aborted.', 'kat500:serve_kat500_remote_client')
        except Exception as ex:
            logging.error(f'client {client_name} exception in serve_network_client: {type(ex)} {ex}',
                          'kat500:serve_kat500_remote_client')
        finally:
            logging.info(f'client {client_name} disconnected', 'kat500:serve_kat500_remote_client')
            found_network_client = None
            for network_client in self.network_clients:
                if network_client.client_name == client_data.client_name:
                    found_network_client = network_client
                    break
            if found_network_client is not None:
                self.network_clients.remove(found_network_client)
                logging.info(f'client {client_name} removed from network_clients list.',
                             'kat500:serve_kat500_remote_client')
        tc = milliseconds()
        logging.info(f'client {client_name} disconnected, elapsed time {((tc - t0) / 1000.0):6.3f} seconds',
                     'kat500:serve_kat500_remote_client')
