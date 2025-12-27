#
# Superclass for device management for KAT500 & KPA-500
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

import asyncio
from collections import deque
import micro_logging as logging
from serialport import SerialPort

class ClientData:
    """
    class holds data for each KPA500-Remote (Elecraft) client.
    """
    def __init__(self, client_name):
        self.client_name = client_name
        self.update_list = deque((), 32, 1)
        self.update_set = set()
        self.authorized = False
        self.connected = True
        self.last_activity = 0


class BufferAndLength:
    def __init__(self, buffer: bytearray):
        self.buffer = buffer
        self._max_size = len(buffer)
        self.bytes_received = 0

    def data(self) -> bytearray:
        return self.buffer[:self.bytes_received]

    def __str__(self) -> str:
        return self.buffer[:self.bytes_received].decode()

    def clear(self):
        self.bytes_received = 0

    def last(self) -> int | None:
        if self.bytes_received > 0:
            return self.buffer[self.bytes_received-1]
        else:
            return None


class KDevice:
    def __init__(self, username=None, password=None, port_name=None, data_size=0):
        self.username = username
        self.password = password
        self.port_name = port_name
        self.device_command_queue = deque((), 64, 1)
        self.network_clients = []
        self.device_data = ['0'] * data_size
        self.device_port = SerialPort(name=port_name, baudrate=38400, timeout=0)  # timeout is zero for non-blocking

    def enqueue_command(self, command):
        dcq = self.device_command_queue
        if isinstance(command, bytes):
            dcq.append(command)
        elif isinstance(command, tuple):
            for c in command:
                dcq.append(c)
        else:
            logging.warning(f'enqueue command received command of type {type(command)} which was not processed.',
                            'enqueue_command')

    def dequeue_command(self):
        dcq = self.device_command_queue
        if len(dcq) == 0:
            return None
        return dcq.popleft()

    def update_device_data(self, index, value):
        if self.device_data[index] != value:
            self.device_data[index] = value
            for client in self.network_clients:
                if index not in client.update_set:
                    client.update_list.append(index)
                    client.update_set.add(index)

    async def device_send_receive(self, message, buf_and_length, timeout=5.0, retries=1):
        retries_left = retries
        while retries_left > 0:
            retries_left -= 1
            device_port = self.device_port
            # empty the receiver buffer
            while True:
                buf_and_length.bytes_received = device_port.readinto(buf_and_length.buffer)
                if  buf_and_length.bytes_received > 0:
                    logging.warning(f'waiting to send "{message}", rx buffer was not empty: "{buf_and_length}".',
                             'kdevice:device_send_receive')
                else:
                    break
            device_port.write(message)
            device_port.flush()
            await asyncio.sleep(0.1)  # TODO FIXME

            while timeout > 0:
                await asyncio.sleep(0.01)
                timeout -= 0.01
                if device_port.any() > 0:
                    break
            buf_and_length.bytes_received = device_port.readinto(buf_and_length.buffer)
            if buf_and_length.bytes_received > 0:
                return
            if retries_left > 0:
                logging.debug(f'received {buf_and_length.bytes_received} bytes response to {message}, {retries_left} retries left.',
                              'kdevice:device_send_receive')
            else:
                logging.debug(f'timeout waiting for response to "{message}".', 'kdevice:device_send_receive')

    @staticmethod
    async def read_network_client(reader):
        try:
            data = await reader.readline()
            return data.decode().strip()
        # except ConnectionResetError as cre:  # micropython does not support ConnectionResetError
        #    logging.warning(f'ConnectionResetError in read_network_client: {str(cre)}', 'read_network_client')
        except Exception as ex:
            logging.error(f'exception in read_network_client: {str(ex)}', 'kdevice:read_network_client')
            # raise ex
        return None
