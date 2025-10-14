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
import micro_logging as logging
from serialport import SerialPort

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
    def __init__(self, username=None, password=None, port_name=None, data_size=0):
        self.username = username
        self.password = password
        self.port_name = port_name
        self.device_command_queue = []
        self.network_clients = []
        self.device_data = ['0'] * data_size
        self.device_port = SerialPort(name=port_name, baudrate=38400, timeout=0)  # timeout is zero for non-blocking

    def enqueue_command(self, command):
        dcq = self.device_command_queue
        if isinstance(command, bytes):
            dcq.append(command)
        elif isinstance(command, tuple):
            dcq.extend(command)
        else:
            logging.warning(f'enqueue command received command of type {type(command)} which was not processed.',
                            'enqueue_command')

    def dequeue_command(self):
        dcq = self.device_command_queue
        if len(dcq) == 0:
            return None
        return dcq.pop(0)

    def update_device_data(self, index, value):
        if self.device_data[index] != value:
            self.device_data[index] = value
            for network_client in self.network_clients:
                if index not in network_client.update_list:
                    network_client.update_list.append(index)

    async def device_send_receive(self, message, buf_and_length, wait_time=0.50, retries=1):
        while retries > 0:
            retries -= 1
            device_port = self.device_port
            # empty the receive buffer
            while device_port.readinto(buf_and_length.buffer) > 0:
                logging.warning(f'waiting to send "{message}", rx buffer was not empty: "{buf_and_length.buffer}"')
            device_port.write(message)
            device_port.flush()
            while wait_time > 0:
                await asyncio.sleep(0.01)
                wait_time -= 0.01
                if device_port.any() > 0:
                    break
            buf_and_length.bytes_received = device_port.readinto(buf_and_length.buffer)
            if buf_and_length.bytes_received > 0:
                return
            if retries > 0:
                logging.debug(f'received {buf_and_length.bytes_received} bytes response to {message}, retrying')

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
