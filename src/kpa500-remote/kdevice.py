#
# Superclass for device management for KAT500 & KPA-500
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

from serialport import SerialPort
from utils import upython

if upython:
    import uasyncio as asyncio
else:
    import asyncio


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


class KDevice:
    def __init__(self, username=None, password=None, port_name=None):
        self.username = username
        self.password = password
        self.port_name = port_name
        self.device_command_queue = []
        self.network_clients = []
        self.device_port = SerialPort(name=port_name, baudrate=38400, timeout=0)  # timeout is zero for non-blocking

    def enqueue_command(self, command):
        if isinstance(command, bytes):
            self.device_command_queue.append(command)
        elif isinstance(command, tuple):
            self.device_command_queue.extend(command)
        else:
            print(f'enqueue command received command of type {type(command)} which was not processed.')

    def dequeue_command(self):
        if len(self.device_command_queue) == 0:
            return None
        return self.device_command_queue.pop(0)

    def update_device_data(self, index, value):
        if self.device_data[index] != value:
            self.device_data[index] = value
            for network_client in self.network_clients:
                if index not in network_client.update_list:
                    network_client.update_list.append(index)

    async def device_send_receive(self, message, buf_and_length, timeout=0.05):
        # should the read buffer be flushed? can only read to drain
        while len(self.device_port.read()) > 0:
            pass
        self.device_port.write(message)
        self.device_port.flush()
        await asyncio.sleep(timeout)
        buf_and_length.bytes_received = self.device_port.readinto(buf_and_length.buffer)

    @staticmethod
    async def read_network_client(reader):
        try:
            data = await reader.readline()
            return data.decode().strip()
        except ConnectionResetError as cre:
            print(f'ConnectionResetError in read_network_client: {str(cre)}')
        except Exception as ex:
            print(ex)
            print(f'exception in read_network_client: {str(ex)}')
            raise ex
        return None
