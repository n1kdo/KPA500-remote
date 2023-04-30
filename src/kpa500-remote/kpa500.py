#
# KPA500 & KPA-500 Remote client data
#
# Copyright 2023, J. B. Otterson N1KDO.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#  1. Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#  2. Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
# OF THE POSSIBILITY OF SUCH DAMAGE.

# disable pylint import error
# pylint: disable=E0401

import sys
from serialport import SerialPort

impl_name = sys.implementation.name
if impl_name == 'cpython':
    import asyncio
else:
    import uasyncio as asyncio


class ClientData:
    """
    class holds data for each KPA500-Remote (Elecraft) client.
    """
    def __init__(self, client_name):
        self.client_name = client_name
        self.update_list = []
        self.authorized = False
        self.connected = True
        self.last_activity = 0


class BufferAndLength:
    def __init__(self, buffer):
        self.buffer = buffer
        self.bytes_received = 0

    def data(self):
        return self.buffer[:self.bytes_received]


async def kpa500_send_receive(amp_port, message, buf_and_length, timeout=0.05):
    # should the read buffer be flushed? can only read to drain
    while len(amp_port.read()) > 0:
        pass
    amp_port.write(message)
    amp_port.flush()
    await asyncio.sleep(timeout)
    buf_and_length.bytes_received = amp_port.readinto(buf_and_length.buffer)


class KPA500:
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
                       b'^SN;',  # Serial Number
                       b'^ON;',  # on/off status
                       b'^FC;')  # minimum fan speed.

    normal_queries = (b'^FL;',  # faults
                      b'^WS;',  # watts/swr
                      b'^VI;',  # volts/amps
                      b'^OS;',  # standby/operate
                      b'^TM;',  # temperature
                      b'^BN;',  # band
                      b'^SP;',  # speaker
                      )

    def __init__(self):
        self.kpa500_data = ['0'] * 19
        self.kpa500_command_queue = []

        self.kpa500_data[1] = '1'
        self.kpa500_data[8] = '160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m'
        self.kpa500_data[9] = '000'
        self.kpa500_data[10] = '000'
        self.kpa500_data[11] = '000'
        self.kpa500_data[13] = '00'
        self.kpa500_data[14] = '0,6,0'
        self.kpa500_data[15] = '0,10,0'
        self.kpa500_data[18] = '4'
        self.network_clients = []
        self.amp_port = SerialPort(baudrate=38400, timeout=0)  # timeout is zero because we do not want to block

    def band_label_to_number(self, label):
        for i, band_name in enumerate(self.band_number_to_name):
            if label == band_name:
                return i
        return None

    def enqueue_command(self, command):
        if isinstance(command, bytes):
            self.kpa500_command_queue.append(command)
        elif isinstance(command, tuple):
            self.kpa500_command_queue.extend(command)
        else:
            print(f'enqueue command received command of type {type(command)} which was not processed.')

    def dequeue_command(self):
        if len(self.kpa500_command_queue) == 0:
            return None
        return self.kpa500_command_queue.pop(0)

    def get_fault_text(self, fault_code):
        if fault_code.isdigit():
            fault_num = int(fault_code)
            if fault_num < len(self.fault_texts):
                return self.fault_texts[fault_num]
        return fault_code

    def process_kpa500_message(self, msg):
        if msg is None or len(msg) == 0:
            print('empty message')
        if msg == ';':
            return
        if msg[0] != '^':
            print(f'bad data: {msg}')
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
                self.update_kpa500_data(5, band_name)
        elif cmd == 'FC':  # fan minimum speed
            fan_min = int(cmd_data)
            self.update_kpa500_data(17, str(fan_min))
        elif cmd == 'FL':
            fault = self.get_fault_text(cmd_data)
            self.update_kpa500_data(6, fault)
            # self.update_kpa500_data(2, '0' if cmd_data == '00' else '1')
        elif cmd == 'ON':
            self.update_kpa500_data(4, cmd_data)
        elif cmd == 'OS':
            operate = cmd_data
            standby = '1' if cmd_data == '0' else '0'
            self.update_kpa500_data(0, operate)
            self.update_kpa500_data(1, standby)
        elif cmd == 'RVM':  # version
            self.update_kpa500_data(7, cmd_data)
        elif cmd == 'SN':  # serial number
            self.update_kpa500_data(16, cmd_data)
        elif cmd == 'SP':  # speaker on/off
            self.update_kpa500_data(3, cmd_data)
        elif cmd == 'TM':  # temp
            temp = int(cmd_data)
            self.update_kpa500_data(12, str(temp))
        elif cmd == 'VI':  # volts
            split_cmd_data = cmd_data.split(' ')
            if len(split_cmd_data) == 2:
                volts = split_cmd_data[0]  # int(split_cmd_data[0])
                amps = split_cmd_data[1]  # int(split_cmd_data[1])  # int breaks Elecraft client "Current: PTT OFF"
                if amps != '000' and amps[0] == '0':
                    amps = amps[1:]
                self.update_kpa500_data(13, str(volts))
                self.update_kpa500_data(9, str(amps))
        elif cmd == 'WS':  # watts/power & swr
            split_cmd_data = cmd_data.split(' ')
            if len(split_cmd_data) == 2:
                watts = split_cmd_data[0]  # the Elecraft client likes '000' for no "SWR: NO RF"
                if watts != '000':
                    while len(watts) > 1 and watts[0] == '0':
                        watts = watts[1:]
                self.update_kpa500_data(10, str(watts))
                swr = split_cmd_data[1]
                if swr != '000' and swr[0] == '0':
                    swr = swr[1:]
                self.update_kpa500_data(11, str(swr))
        else:
            print(f'unprocessed command {cmd} with data {cmd_data}')

    def set_amp_off_data(self):
        # reset all the indicators when the amp is turned off.
        self.update_kpa500_data(0, '0')  # OPER button
        self.update_kpa500_data(1, '1')  # STBY button
        self.update_kpa500_data(4, '0')  # POWER button
        self.update_kpa500_data(9, '000')  # CURRENT meter
        self.update_kpa500_data(10, '000')  # POWER meter
        self.update_kpa500_data(11, '000')  # SWR meter
        self.update_kpa500_data(12, '0')  # TEMPERATURE meter
        self.update_kpa500_data(13, '00')  # VOLTAGE meter
        self.update_kpa500_data(17, '0')  # Fan Minimum speed slider

    def update_kpa500_data(self, index, value):
        if self.kpa500_data[index] != value:
            self.kpa500_data[index] = value
            for network_client in self.network_clients:
                if index not in network_client.update_list:
                    network_client.update_list.append(index)

    # KPA500 amplifier polling code
    async def kpa500_server(self, verbosity=3):
        """
        this manages the connection to the physical amplifier
        :param verbosity: how much logging?
        :return: None
        """

        amp_state = 0  # 0 not connected, 1 online state unknown , 2 power off, 3 power on
        bl = BufferAndLength(bytearray(16))
        next_command = 0
        run_loop = True

        while run_loop:
            if amp_state == 0:  # unknown / no response state
                # poke at the amplifier -- is it connected?
                await kpa500_send_receive(self.amp_port, b';', bl)
                # connected will return a ';' here
                if bl.bytes_received != 1 or bl.buffer[0] != 59:
                    self.update_kpa500_data(6, 'NO AMP')
                else:
                    amp_state = 1
                    if verbosity > 3:
                        print('amp state 0-->1')
            elif amp_state == 1:  # apparently connected
                # ask if it is turned on.
                await kpa500_send_receive(self.amp_port, b'^ON;', bl)  # hi there.
                # is b'^ON1;' when amp is on.
                # is b'^ON;' when amp is off
                # is b'' when amp is not found.
                if bl.bytes_received == 0:
                    amp_state = 0
                    self.update_kpa500_data(4, '0')  # not powered
                    self.update_kpa500_data(6, 'NO AMP')
                    if verbosity > 3:
                        print('1: no response, amp state 1-->0')
                elif bl.bytes_received == 5 and bl.buffer[3] == 49:  # '1', amp appears on
                    amp_state = 3  # amp is powered on.
                    self.update_kpa500_data(4, '1')
                    self.update_kpa500_data(6, 'AMP ON')
                    self.enqueue_command(self.initial_queries)
                    if verbosity > 3:
                        print('amp state 1-->3')
                elif bl.bytes_received == 4 and bl.buffer[3] == 59:  # ';', amp connected but off.
                    amp_state = 2
                    self.update_kpa500_data(4, '0')
                    self.update_kpa500_data(6, 'AMP OFF')
                    if verbosity > 3:
                        print('amp state 1-->2')
                else:
                    if verbosity > 1:
                        print(f'1: unexpected data {bl.buffer[:bl.bytes_received]}')
            elif amp_state == 2:  # connected, power off.
                query = self.dequeue_command()
                # throw away any queries except the ON command.
                if query is not None and query == b'^ON1;':  # turn on amplifier
                    await kpa500_send_receive(self.amp_port, b'P', bl)
                    self.update_kpa500_data(6, 'Powering On')
                    await asyncio.sleep(1.50)
                    amp_state = 0  # test state again.
                    if verbosity > 3:
                        print('amp state 2-->0')
                else:
                    await kpa500_send_receive(self.amp_port, b'^ON;', bl, timeout=1.5)  # hi there.
                    # is b'^ON1;' when amp is on.
                    # is b'^ON;' when amp is off
                    # is b'' when amp is not found.
                    if bl.bytes_received == 0:
                        amp_state = 1
                        self.update_kpa500_data(4, '0')  # not powered
                        self.update_kpa500_data(6, 'NO AMP')
                        if verbosity > 3:
                            print('no data, amp state 2-->1')
                    elif bl.bytes_received == 5 and bl.buffer[3] == 49:  # '1', amp appears on
                        amp_state = 3  # amp is powered on.
                        self.update_kpa500_data(4, '1')
                        self.update_kpa500_data(6, 'AMP ON')
                        self.enqueue_command(self.initial_queries)
                        if verbosity > 3:
                            print('amp state 2-->3')
                    elif bl.bytes_received == 4 and bl.buffer[3] == 59:  # ';', amp connected but off.
                        pass  # this is the expected result when amp is off
                    else:
                        if verbosity > 3:
                            print(f'2: unexpected data {bl.buffer[:bl.bytes_received]}')
            elif amp_state == 3:  # connected, power on.
                query = self.dequeue_command()
                if query is None:
                    query = self.normal_queries[next_command]
                    if next_command == len(self.normal_queries) - 1:  # this is the last one
                        next_command = 0
                    else:
                        next_command += 1
                await kpa500_send_receive(self.amp_port, query, bl)
                if query == b'^ON0;':
                    amp_state = 1
                    if verbosity > 3:
                        print('power off command, amp state 3-->1')
                    self.update_kpa500_data(6, 'PWR OFF')
                    self.set_amp_off_data()
                    await asyncio.sleep(1.50)
                else:
                    if bl.bytes_received > 0:
                        self.process_kpa500_message(bl.data().decode())
                    else:
                        amp_state = 0
                        self.update_kpa500_data(6, 'NO AMP')
                        self.set_amp_off_data()
                        if verbosity > 3:
                            print('no response, amp state 3-->0')
            else:
                print(f'invalid amp state: {amp_state}, bye bye.')
                run_loop = False

            await asyncio.sleep(0.025)  # 40/sec
