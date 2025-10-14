#
# KPA500 & KPA-500 Remote client data
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
__version__ = '0.9.1'

# disable pylint import error
# pylint: disable=E0401

import asyncio
import gc
import micro_logging as logging
from kdevice import KDevice, ClientData, BufferAndLength
from utils import upython, milliseconds


if upython:
    from asyncio import TimeoutError
else:
    from asyncio.exceptions import TimeoutError


class KPA500(KDevice):
    band_number_to_name = ('160m', '80m', '60m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m')
    # noinspection SpellCheckingInspection
    key_names = (
        b'amp::button::OPER',            # 00 : 0 or 1
        b'amp::button::STBY',            # 01 : 0 or 1
        b'amp::button::CLEAR',           # 02 : 0 or 1
        b'amp::button::SPKR',            # 03 : 0 or 1
        b'amp::button::PWR',             # 04 : 0 or 1
        b'amp::dropdown::Band',          # 05 : string
        b'amp::fault',                   # 06 : string
        b'amp::firmware',                # 07 : string
        b'amp::list::Band',              # 08 : string
        b'amp::meter::Current',          # 09 : integer
        b'amp::meter::Power',            # 10 : integer
        b'amp::meter::SWR',              # 11 : integer
        b'amp::meter::Temp',             # 12 : integer
        b'amp::meter::Voltage',          # 13 : integer
        b'amp::range::Fan Speed',        # 14 : string
        b'amp::range::PWR Meter Hold',   # 15 : string
        b'amp::serial',                  # 16 : string
        b'amp::slider::Fan Speed',       # 17 : integer
        b'amp::slider::PWR Meter Hold',  # 18 : integer
    )

    fault_texts = ('AMP ON',    # 0
                   '01',        # 1
                   'HI CURR',   # 2
                   '03',        # 3
                   'HI TEMP',   # 4
                   '05',        # 5
                   'PWRIN HI',  # 6
                   '07',        # 7
                   '60V HIGH',  # 8
                   'REFL HI',   # 9
                   '10',        # 10
                   'PA DISS',   # 11
                   'POUT HI',   # 12
                   '60V FAIL',  # 13
                   '270V ERR',  # 14
                   'GAIN ERR',  # 15
                   )

    initial_queries = (b';',  # attention!
                       b'^RVM;',  # get version
                       b'^SN;',   # Serial Number
                       b'^ON;',   # on/off status
                       b'^FC;')   # minimum fan speed.

    normal_queries = (b'^FL;',  # faults
                      b'^WS;',  # watts/swr
                      b'^VI;',  # volts/amps
                      b'^OS;',  # standby/operate
                      b'^TM;',  # temperature
                      b'^BN;',  # band
                      b'^SP;',  # speaker
                      )

    def __init__(self, username=None, password=None, port_name=None):
        super().__init__(username, password, port_name, len(self.key_names))

        self.device_data[1] = '1'
        self.device_data[8] = '160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m'
        self.device_data[9] = '000'
        self.device_data[10] = '000'
        self.device_data[11] = '000'
        self.device_data[13] = '00'
        self.device_data[14] = '0,6,0'
        self.device_data[15] = '0,10,0'
        self.device_data[18] = '4'

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

    def process_kpa500_message(self, msg):
        if msg is None or len(msg) == 0:
            logging.warning('empty message', 'process_kpa500_message')
        if msg == ';':
            return
        if msg[0] != '^':
            logging.warning(f'bad data: {msg}', 'process_kpa500_message')
            return
        command_length = 3  # including the ^
        if msg[command_length] >= 'A':  # there is another letter
            command_length = 4

        cmd = msg[1:command_length]
        semi_offset = msg.find(';')
        cmd_data = msg[command_length:semi_offset]
        if cmd == 'BN':  # band
            band_num = int(cmd_data)
            if band_num <= 10:
                band_name = self.band_number_to_name[band_num]
                self.update_device_data(5, band_name)
        elif cmd == 'FC':  # fan minimum speed
            fan_min = int(cmd_data)
            self.update_device_data(17, str(fan_min))
        elif cmd == 'FL':
            fault = self.get_fault_text(cmd_data)
            self.update_device_data(6, fault)
            # self.update_kpa500_data(2, '0' if cmd_data == '00' else '1')
        elif cmd == 'ON':
            self.update_device_data(4, cmd_data)
        elif cmd == 'OS':
            operate = cmd_data
            standby = '1' if cmd_data == '0' else '0'
            self.update_device_data(0, operate)
            self.update_device_data(1, standby)
        elif cmd == 'RVM':  # version
            self.update_device_data(7, cmd_data)
        elif cmd == 'SN':  # serial number
            self.update_device_data(16, cmd_data)
        elif cmd == 'SP':  # speaker on/off
            self.update_device_data(3, cmd_data)
        elif cmd == 'TM':  # temp
            temp = int(cmd_data)
            self.update_device_data(12, str(temp))
        elif cmd == 'VI':  # volts
            split_cmd_data = cmd_data.split(' ')
            if len(split_cmd_data) == 2:
                volts = split_cmd_data[0]  # int(split_cmd_data[0])
                amps = split_cmd_data[1]  # int(split_cmd_data[1])  # int breaks Elecraft client "Current: PTT OFF"
                if amps != '000' and amps[0] == '0':
                    amps = amps[1:]
                self.update_device_data(13, str(volts))
                self.update_device_data(9, str(amps))
        elif cmd == 'WS':  # watts/power & swr
            split_cmd_data = cmd_data.split(' ')
            if len(split_cmd_data) == 2:
                watts = split_cmd_data[0]  # the Elecraft client likes '000' for no "SWR: NO RF"
                if watts != '000':
                    while len(watts) > 1 and watts[0] == '0':
                        watts = watts[1:]
                self.update_device_data(10, str(watts))
                swr = split_cmd_data[1]
                if swr != '000' and swr[0] == '0':
                    swr = swr[1:]
                self.update_device_data(11, str(swr))
        else:
            logging.warning(f'unprocessed command {cmd} with data {cmd_data}', 'process_kpa500_message')

    def set_amp_off_data(self):
        # reset all the indicators when the amp is turned off.
        udd = self.update_device_data
        udd(0, '0')  # OPER button
        udd(1, '1')  # STBY button
        udd(4, '0')  # POWER button
        udd(9, '000')  # CURRENT meter
        udd(10, '000')  # POWER meter
        udd(11, '000')  # SWR meter
        udd(12, '0')  # TEMPERATURE meter
        udd(13, '00')  # VOLTAGE meter
        udd(17, '0')  # Fan Minimum speed slider

    # KPA500 amplifier polling code
    async def kpa500_server(self):
        """
        this manages the connection to the physical amplifier
        :return: None
        """

        amp_state = 0  # 0 not connected, 1 online state unknown , 2 power off, 3 power on
        bl = BufferAndLength(bytearray(16))
        next_command = 0
        run_loop = True

        while run_loop:
            if amp_state == 0:  # unknown / no response state
                # poke at the amplifier -- is it connected?
                await self.device_send_receive(b';', bl)
                # connected will return a ';' here
                if bl.bytes_received != 1 or bl.buffer[0] != 59:
                    self.update_device_data(6, 'NO AMP')
                else:
                    amp_state = 1
                    logging.debug('amp state 0-->1', 'kpa500_server')
            elif amp_state == 1:  # apparently connected
                # ask if it is turned on.
                await self.device_send_receive(b'^ON;', bl)  # hi there.
                # is b'^ON1;' when amp is on.
                # is b'^ON;' when amp is off
                # is b'' when amp is not found.
                if bl.bytes_received == 0:
                    amp_state = 0
                    self.update_device_data(4, '0')  # not powered
                    self.update_device_data(6, 'NO AMP')
                    logging.debug('1: no response, amp state 1-->0', 'kpa500_server')
                elif bl.bytes_received == 5 and bl.buffer[3] == 49:  # '1', amp appears on
                    amp_state = 3  # amp is powered on.
                    self.update_device_data(4, '1')
                    self.update_device_data(6, 'AMP ON')
                    self.enqueue_command(self.initial_queries)
                    logging.debug('amp state 1-->3', 'kpa500_server')
                elif bl.bytes_received == 4 and bl.buffer[3] == 59:  # ';', amp connected but off.
                    amp_state = 2
                    self.update_device_data(4, '0')
                    self.update_device_data(6, 'AMP OFF')
                    logging.debug('amp state 1-->2', 'kpa500_server')
                else:
                    logging.warning(f'1: unexpected data {bl.buffer[:bl.bytes_received]}', 'kpa500_server')
            elif amp_state == 2:  # connected, power off.
                query = self.dequeue_command()
                # throw away any queries except the ON command.
                if query is not None and query == b'^ON1;':  # turn on amplifier
                    await self.device_send_receive(b'P', bl)
                    self.update_device_data(6, 'Powering On')
                    await asyncio.sleep(1.50)
                    amp_state = 0  # test state again.
                    logging.debug('amp state 2-->0', 'kpa500_server')
                else:
                    await self.device_send_receive(b'^ON;', bl, wait_time=1.5)  # hi there.
                    # is b'^ON1;' when amp is on.
                    # is b'^ON;' when amp is off
                    # is b'' when amp is not found.
                    if bl.bytes_received == 0:
                        amp_state = 1
                        self.update_device_data(4, '0')  # not powered
                        self.update_device_data(6, 'NO AMP')
                        logging.debug('no data, amp state 2-->1', 'kpa500_server')
                    elif bl.bytes_received == 5 and bl.buffer[3] == 49:  # '1', amp appears on
                        amp_state = 3  # amp is powered on.
                        self.update_device_data(4, '1')
                        self.update_device_data(6, 'AMP ON')
                        self.enqueue_command(self.initial_queries)
                        logging.debug('amp state 2-->3', 'kpa500_server')
                    elif bl.bytes_received == 4 and bl.buffer[3] == 59:  # ';', amp connected but off.
                        pass  # this is the expected result when amp is off
                    else:
                        logging.debug(f'2: unexpected data {bl.buffer[:bl.bytes_received]}', 'kpa500_server')
            elif amp_state == 3:  # connected, power on.
                query = self.dequeue_command()
                if query is None:
                    query = self.normal_queries[next_command]
                    if next_command == len(self.normal_queries) - 1:  # this is the last one
                        next_command = 0
                    else:
                        next_command += 1
                await self.device_send_receive(query, bl)
                if query == b'^ON0;':
                    amp_state = 1
                    logging.debug('power off command, amp state 3-->1', 'kpa500_server')
                    self.update_device_data(6, 'PWR OFF')
                    self.set_amp_off_data()
                    await asyncio.sleep(1.50)
                else:
                    if bl.bytes_received > 0:
                        self.process_kpa500_message(bl.data().decode())
                    else:
                        amp_state = 0
                        self.update_device_data(6, 'NO AMP')
                        self.set_amp_off_data()
                        logging.debug('no response, amp state 3-->0', 'kpa500_server')
            else:
                logging.error(f'invalid amp state: {amp_state}, bye bye.', 'kpa500_server')
                run_loop = False

            await asyncio.sleep(0.025)  # 40/sec

    async def serve_kpa500_remote_client(self, reader, writer):
        """
        this provides KPA500-Remote compatible control.
        """
        # verbosity = 3  # 3 is info, 4 is debug, 5 is trace, or something like that.
        t0 = milliseconds()
        extra = writer.get_extra_info('peername')
        client_name = f'{extra[0]}:{extra[1]}'
        client_data = ClientData(client_name)
        client_data.update_list.extend((7, 16, 6, 0, 1, 2, 3, 4, 8, 5, 9, 10, 11, 12, 13, 14, 15, 17, 18))  # items to send.
        self.network_clients.append(client_data)
        logging.info(f'client {client_name} connected', 'kpa500:serve_kpa500_remote_client')
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
                    if len(message) == 0:  # keepalive?
                        logging.debug(f'RECEIVED keepalive FROM client {client_name}',
                                      'kpa500:serve_kpa500_remote_client')
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
                        logging.debug(f'sending "{response.decode().strip()}"', 'kpa500:serve_kpa500_remote_client')
                    else:
                        if client_data.authorized:
                            # noinspection SpellCheckingInspection
                            if message.startswith('amp::button::CLEAR::'):
                                self.enqueue_command(b'^FLC;')
                            elif message.startswith('amp::button::OPER::'):
                                value = message[19:]
                                if value == '1':
                                    command = b'^OS1;^OS;'
                                else:
                                    command = b'^OS0;^OS;'
                                self.enqueue_command(command)
                            elif message.startswith('amp::button::STBY::'):
                                value = message[19:]
                                if value == '0':
                                    command = b'^OS1;^OS;'
                                else:
                                    command = b'^OS0;^OS;'
                                self.enqueue_command(command)
                            elif message.startswith('amp::button::PWR::'):
                                value = message[18:]
                                if value == '1':
                                    command = b'^ON1;'
                                else:
                                    command = b'^ON0;'
                                self.enqueue_command(command)
                            elif message.startswith('amp::button::SPKR::'):
                                value = message[19:]
                                if value == '1':
                                    command = b'^SP1;'
                                else:
                                    command = b'^SP0;'
                                self.enqueue_command(command)
                            elif message.startswith('amp::dropdown::Band::'):
                                value = message[21:]
                                band_number = self.band_label_to_number(value)
                                if band_number is not None:
                                    command = f'^BN{band_number:02d};'.encode()
                                    self.enqueue_command(command)
                            elif message.startswith('amp::slider::Fan Speed::'):
                                value = message[24:]
                                command = f'^FC{value};^FC;'.encode()
                                self.enqueue_command(command)
                            else:
                                logging.info(f'unhandled message "{message}"', 'kpa500:serve_kpa500_remote_client')
                else:  # response was None
                    if not timed_out:
                        logging.info(f'client {client_data} response was None, setting connected=false',
                                     'kpa500:serve_kpa500_remote_client')
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
                                  'serve_kpa500_remote_client')

                since_last_activity = milliseconds() - client_data.last_activity
                if since_last_activity > 15000:
                    writer.write(b'\n')
                    await writer.drain()
                    client_data.last_activity = milliseconds()
                    logging.debug(f'SENT keepalive TO client {client_name}',
                                 'kpa500:serve_kpa500_remote_client')
                gc.collect()

            # connection closing
            logging.info(f'client {client_name} connection closing...', 'serve_kpa500_remote_client')
            writer.close()
            await writer.wait_closed()
        except Exception as ex:
            logging.error(f'client {client_name} exception in serve_network_client: {type(ex)} {ex}',
                          'kpa500:serve_kpa500_remote_client')
            raise ex
        finally:
            logging.info(f'client {client_name} disconnected', 'serve_kpa500_remote_client')
            found_network_client = None
            for network_client in self.network_clients:
                if network_client.client_name == client_data.client_name:
                    found_network_client = network_client
                    break
            if found_network_client is not None:
                self.network_clients.remove(found_network_client)
                logging.info(f'client {client_name} removed from network_clients list.',
                             'kpa500:serve_kpa500_remote_client')
        tc = milliseconds()
        logging.info(f'client {client_name} disconnected, elapsed time {((tc - t0) / 1000.0):6.3f} seconds',
                     'kpa500:serve_kpa500_remote_client')
