#
# KAT500 & KAT-500 Remote client data
#
__author__ = 'J. B. Otterson'
__copyright__ = """
Copyright 2022, 2026, J. B. Otterson N1KDO.
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
__version__ = '0.9.8'  # 2026-09-03

# disable pylint import error
# pylint: disable=E0401

import asyncio
import micro_logging as logging

from kdevice import KDevice, ClientData, BufferAndLength
from utils import upython, milliseconds, elapsed_ms, safe_int, LineReader

if upython:
    from asyncio import TimeoutError
else:
    from asyncio.exceptions import TimeoutError


class KAT500(KDevice):
    antenna_number_to_name = (b'One', b'Two', b'Three')
    band_number_to_name = (b'160m', b'80m', b'60m', b'40m', b'30m', b'20m', b'17m', b'15m', b'12m', b'10m', b'6m')
    mode_name_dict = {b'M': b'Manual', b'A': b'Auto', b'B': b'Bypass'}
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

    fault_texts = (b'NO FAULT',                   # 0
                   b'NO MATCH',                   # 1
                   b'POWER ABOVE DESIGN LIMIT',   # 2
                   b'POWER ABOVE RELAY LIMIT',    # 3
                   b'SWR ABOVE THRESHOLD',        # 4
                   b'NO TUNER',                   # 5 n1kdo extension
                   b'POWERING UP',                # 6 n1kdo extension
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

    def __init__(self, username:bytes|None=None, password:bytes|None=None, port_name=None):
        super().__init__(username, password, port_name, len(self.key_names))

        self.device_data[4] = b'1'
        self.device_data[6] = b''
        self.device_data[7] = b''
        self.device_data[8] = b''
        self.device_data[13] = b'1.0'
        self.device_data[14] = b'1.0'

    def process_kat500_message(self, msg):
        if not msg:
            logging.warning('empty message', 'kat500:process_kat500_message')
            return
        if msg == b';':
            return
        if msg[-1] != 59:  # b';'
            logging.warning(b'bad data: %s' % msg, 'kat500:process_kat500_message')
            return

        cmd = msg[:-1]
        if not cmd:
            return

        if cmd.startswith(b'KAT500'):
            pass  # just eat this.
        elif cmd.startswith(b'VSWRB'):
            self.update_device_data(14, cmd[5:].strip())
        elif cmd.startswith(b'AMPI'):
            self.update_device_data(0, cmd[4:].strip())
        elif cmd.startswith(b'ATTN'):
            self.update_device_data(1, cmd[4:].strip())
        elif cmd.startswith(b'VFWD'):
            self.update_device_data(11, cmd[4:].strip())
        elif cmd.startswith(b'VRFL'):
            self.update_device_data(12, cmd[4:].strip())
        elif cmd.startswith(b'VSWR'):
            self.update_device_data(13, cmd[4:].strip())
        elif cmd.startswith(b'BYP'):
            self.update_device_data(2, cmd[3:])
        elif cmd.startswith(b'FLT'):
            self.update_device_data(9, cmd[3:])
        elif cmd.startswith(b'AN'):
            data = cmd[2:]
            if data:
                antenna_number = safe_int(data)
                if 1 <= antenna_number <= len(self.antenna_number_to_name):
                    antenna = self.antenna_number_to_name[antenna_number - 1]
                    self.update_device_data(6, antenna)
        elif cmd.startswith(b'BN'):
            data = cmd[2:]
            if data:
                band_number = safe_int(data)
                if 0 <= band_number < len(self.band_number_to_name):
                    band_name = self.band_number_to_name[band_number]
                    self.update_device_data(7, band_name)
        elif cmd.startswith(b'MD'):
            data = cmd[2:]
            if data:
                mode_name = self.mode_name_dict.get(data) or data
                self.update_device_data(8, mode_name)
        elif cmd.startswith(b'PS'):
            data = cmd[2:]
            if data:
                self.update_device_data(4, data)
        elif cmd.startswith(b'RV'):
            data = cmd[2:]
            logging.info(b'Revision %s' % data if data else 'Revision Query', 'kat500:process_kat500_message')
        elif cmd.startswith(b'SL'):
            data = cmd[2:]
            logging.info(b'SLeep query %s' % data if data else 'SLeep Query', 'kat500:process_kat500_message')
        elif cmd.startswith(b'SN'):
            data = cmd[2:]
            logging.info(b'Serial Number %s' % data if data else 'Serial Number Query', 'kat500:process_kat500_message')
        elif cmd.startswith(b'TP'):
            data = cmd[2:]
            if data:
                self.update_device_data(5, data)  # update tuning status
        elif cmd.startswith(b'F'):
            data = cmd[1:]
            if data:
                self.update_device_data(10, data)
        else:
            logging.error(b'unhandled: %s' % msg, 'kat500:process_kat500_message')

    def set_tuner_off_data(self):
        # reset all the indicators when the amp is turned off.
        self.update_device_data(4, b'0')  # set POWER to not powered
        self.update_device_data(9, b'0')  # set FAULT to not faulted

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
            try:
                if tuner_state == 0:  # unknown / no response state
                    # poke at the tuner -- is it connected?
                    await self.device_send_receive(b';', bl)
                    # connected will return a ';' here
                    if bl.bytes_received != 1 or bl.buffer[0] != 59:
                        self.update_device_data(9, b'5')
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
                        self.update_device_data(4, b'0')  # set POWER to not powered
                        self.update_device_data(9, b'5')  # set FAULT to NO TUNER
                        logging.info('1: no response, amp state 1-->0', 'kat500:kat500_server')
                    elif bl.bytes_received == 4 and bl.buffer[2] == 49:  # '1', tuner appears on
                        tuner_state = 3  # tuner is powered on.
                        self.update_device_data(4, b'1')  # set POWER to POWERED
                        self.update_device_data(9, b'0')  # set FAULT to no fault
                        self.enqueue_command(self.initial_queries)
                        logging.info('tuner state 1-->3', 'kat500:kat500_server')
                    elif bl.bytes_received == 4 and bl.buffer[2] == 48:  # '0', tuner connected but off.
                        tuner_state = 2
                        self.update_device_data(4, b'0')  # set POWER to not powered
                        self.update_device_data(9, b'0')  # set FAULT to no fault
                        logging.info('tuner state 1-->2', 'kat500:kat500_server')
                    else:
                        logging.warning(f'1: unexpected data {bl.buffer[:bl.bytes_received]}', 'kat500:kat500_server')
                elif tuner_state == 2:  # connected, power off.
                    query = self.dequeue_command()
                    # throw away any queries except the ON command.
                    if query is not None and query == b'PS1;':  # turn on tuner
                        await self.device_send_receive(b'PS1;', bl)
                        self.update_device_data(9, b'6')  # set FAULT to powering up
                        await asyncio.sleep(1.50)
                        tuner_state = 0  # test state again.
                        logging.info('tuner state 2-->0', 'kat500:kat500_server')
                    else:
                        await self.device_send_receive(b'PS1;', bl, timeout=1.5)  # hi there.
                        # is b'PS1;' when tuner is on.
                        # is b'PS0;' when tuner is off
                        # is b'' when tuner is not found.
                        if bl.bytes_received == 0:
                            tuner_state = 1
                            self.update_device_data(4, b'0')  # set POWER to not powered
                            self.update_device_data(9, b'5')  # set FAULT to not found
                            logging.info('no data, tuner state 2-->1', 'kat500:kat500_server')
                        elif bl.bytes_received == 4 and bl.buffer[2] == 49:  # '1', tuner appears on
                            tuner_state = 3  # tuner is powered on.
                            self.update_device_data(4, b'1')  # set POWER to powered on
                            self.update_device_data(9, b'0')  # set FAULT to no fault
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
                    await self.device_send_receive(query, bl, retries=3)
                    if query == b'PS0;':
                        tuner_state = 1
                        logging.info('power off command, tuner state 3-->1', 'kat500:kat500_server')
                        self.update_device_data(4, b'0')  # set POWER to not powered
                        self.update_device_data(9, b'0')  # set FAULT  to no fault
                        self.set_tuner_off_data()
                        await asyncio.sleep(1.50)
                    else:
                        if bl.bytes_received > 0:
                            self.process_kat500_message(bl.data())
                        else:
                            tuner_state = 0
                            self.update_device_data(9, b'5')  # set FAULT to NO TUNER
                            self.set_tuner_off_data()
                            logging.info(f'no response to command {query}, tuner state 3-->0', 'kat500:kat500_server')
                else:
                    logging.error(f'invalid tuner state: {tuner_state}, bye bye.', 'kat500:kat500_server')
                    run_loop = False

            except Exception as ex:
                msg = f'kat500_server exception: {type(ex)} {ex}; resetting state for re-detection'
                logging.error(msg, 'kat500:kat500_server')
                tuner_state = 0
                bl = BufferAndLength(bytearray(16))
                next_command = 0
                await asyncio.sleep(1)  # backoff so a persistent fault cannot spin the log
            await asyncio.sleep(0.025)  # 40/sec

    async def serve_kat500_remote_client(self, reader, writer):
        """
        this provides KAT500-Remote compatible control.
        """
        t0 = milliseconds()
        extra = writer.get_extra_info('peername')
        client_name = f'{extra[0]}:{extra[1]}'
        client_data = ClientData(client_name)
        client_data.update_list.extend((9, 4, 5, 0, 1, 2, 3, 6, 8, 7, 13, 14, 11, 12, 10))  # items to send.
        self.network_clients.append(client_data)
        logging.info(f'client {client_name} connected', 'kat500:serve_kat500_remote_client')

        lines = LineReader(reader)
        try:
            while client_data.connected:
                try:
                    # 250 ms idle read timeout: bounds how often the loop iterates when the
                    # client is quiet (each iteration costs a Task + TimeoutError) while keeping
                    # update push latency and the 15 s keepalive check comfortably tight.
                    message = await asyncio.wait_for(self.read_network_client(lines), 0.25)
                    timed_out = False
                except TimeoutError:
                    message = None
                    timed_out = True
                # EOF from read_network_client() arrives as None and is handled below.
                # A bare newline keepalive arrives as b'' and must NOT close the session.
                if message is not None and not timed_out:
                    client_data.last_activity = milliseconds()
                    if len(message) > 0:
                        if logging.should_log(logging.DEBUG):
                            logging.debug(f'RECEIVED "{message}" FROM client {client_name}',
                                          'kat500:serve_kat500_remote_client')
                    if len(message) == 0:  # keepalive?
                        if logging.should_log(logging.DEBUG):
                            logging.debug(f'RECEIVED keepalive FROM client {client_name}',
                                          'kat500:serve_kat500_remote_client')
                    elif message.startswith(b'server::login::'):
                        up_list = message[15:].split(b'::')
                        if len(up_list) != 2:
                            response = b'server::login::invalid::malformed login request provided. ' \
                                       b'Remote control will not be allowed.\n'
                        elif up_list[0] != self.username:
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
                        if logging.should_log(logging.DEBUG):
                            logging.debug(f'sending \"{response.decode().strip()}\"',
                                          'kat500:serve_kat500_remote_client')
                    else:
                        if client_data.authorized:
                            if message.startswith(b'tuner::button::clear::'):
                                self.enqueue_command(b'FLTC;')
                            elif message.startswith(b'tuner::dropdown::Mode::'):
                                value = message[23:]
                                command = None
                                if value == b'Bypass':
                                    command = b'MDB;MD;'
                                elif value == b'Auto':
                                    command = b'MDA;MD;'
                                elif value == b'Manual':
                                    command = b'MDM;MD;'
                                if command is not None:
                                    self.enqueue_command(command)
                            elif message.startswith(b'tuner::dropdown::Antenna::'):
                                value = message[26:]
                                command = None
                                if value == b'One':
                                    command = b'AN1;AN;'
                                elif value == b'Two':
                                    command = b'AN2;AN;'
                                elif value == b'Three':
                                    command = b'AN3;AN;'
                                else:
                                    logging.error(f'confused; antenna dropdown value {value}',
                                                  'kat500:serve_kat500_remote_client')
                                if command is not None:
                                    self.enqueue_command(command)
                            elif message.startswith(b'tuner::button::AMPI::'):
                                value = message[21:]
                                if value == b'1':
                                    command = b'AMPI1;AMPI;'
                                else:
                                    command = b'AMPI0;AMPI;'
                                self.enqueue_command(command)
                            elif message.startswith(b'tuner::button::ATTN::'):
                                value = message[21:]
                                if value == b'1':
                                    command = b'ATTN1;ATTN;'
                                else:
                                    command = b'ATTN0;ATTN;'
                                self.enqueue_command(command)
                            elif message.startswith(b'tuner::button::BYP::'):
                                value = message[20:]
                                if value == b'1':
                                    command = b'BYPB;BYP;'
                                else:
                                    command = b'BYPN;BYP;'
                                self.enqueue_command(command)
                            elif message.startswith(b'tuner::button::Power::'):
                                value = message[22:]
                                if value == b'1':
                                    command = b'PS1;PS;'
                                else:
                                    command = b'PS0;PS;'
                                self.enqueue_command(command)
                            elif message.startswith(b'tuner::button::Tune::'):
                                value = message[21:]
                                if value == b'1':
                                    command = b'FT;TP;'
                                    self.enqueue_command(command)
                            else:
                                logging.info(b'unhandled message from client "%s"' % message,
                                             'kat500:serve_kat500_remote_client')
                else:  # response was None
                    if not timed_out:
                        logging.info(f'client {client_data} response was None, setting connected=false',
                                     'kat500:serve_kat500_remote_client')
                        client_data.connected = False

                # send any outstanding data back...
                if len(client_data.update_list) > 0:
                    while len(client_data.update_list) > 0:
                        index = client_data.update_list.popleft()
                        client_data.update_set.discard(index)
                        try:
                            writer.write(self.key_names[index])
                            payload = b'::%s\n' % self.device_data[index]
                            writer.write(payload)
                        except OSError:
                            client_data.connected = False
                            break
                        if logging.should_log(logging.DEBUG):
                            logging.debug(f'sent \"{self.key_names[index].decode()}{payload.decode().strip()}\"',
                                          'kat500:serve_kat500_remote_client')
                    await writer.drain()
                    client_data.last_activity = milliseconds()

                since_last_activity = elapsed_ms(client_data.last_activity)
                if since_last_activity > 15000:
                    writer.write(b'\n')
                    await writer.drain()
                    client_data.last_activity = milliseconds()
                    if logging.should_log(logging.DEBUG):
                        logging.debug(f'SENT keepalive TO client {client_name}',
                                      'kat500:serve_kat500_remote_client')

            # connection closing
            logging.info(f'client {client_name} connection closing...', 'kat500:serve_kat500_remote_client')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except Exception as ex:
            logging.error(f'client {client_name} exception in serve_network_client: {type(ex)} {ex}',
                          'kat500:serve_kat500_remote_client')
            raise
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
        logging.info(f'client {client_name} disconnected, elapsed time {(elapsed_ms(t0) / 1000.0):6.3f} seconds',
                     'kat500:serve_kat500_remote_client')
