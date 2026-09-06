#
# Superclass for device management for KAT500 & KPA-500
#
__copyright__ = """
Copyright 2022, 2025, 2026 J. B. Otterson N1KDO.
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
__version__ = '0.9.8'  # 2026-08-31

from utils import upython
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
        if upython:
            self.update_list = deque((), 32, 1)  # this is the proper syntax for Micropython.
        else:
            self.update_list = deque((), 32)  # cpython syntax
        self.update_set = set()
        self.authorized = False
        self.connected = True
        self.last_activity = 0


class BufferAndLength:
    def __init__(self, buffer: bytearray):
        self.buffer = buffer
        self._max_size = len(buffer)
        self.bytes_received = 0

    def data(self) -> bytes:
        return bytes(memoryview(self.buffer)[:self.bytes_received])

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
    def __init__(self, username:bytes|None=None, password:bytes|None=None, port_name=None, data_size=0):
        self.username = username
        self.password = password
        self.port_name = port_name
        if upython:
            self.device_command_queue = deque((), 64, 1)  # this is the proper syntax for Micropython.
        else:
            self.device_command_queue = deque((), 64)  # this is the cpython syntax.
        self.network_clients = []
        self.device_data = [b'0'] * data_size
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

    def update_device_data(self, index : int, value : bytes):
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
                    logging.warning(b'waiting to send "%s", rx buffer was not empty: "%s".' % (message, buf_and_length.data()),
                                    'kdevice:device_send_receive')
                else:
                    break
            device_port.write(message)
            device_port.flush()
            # brief grace period for the device to start responding before we begin
            # polling; the read_timeout loop below catches the response whenever it arrives.
            await asyncio.sleep(0.02)

            read_timeout = timeout
            while read_timeout > 0:
                await asyncio.sleep(0.01)
                read_timeout -= 0.01
                if device_port.any() > 0:
                    break
            buf_and_length.bytes_received = device_port.readinto(buf_and_length.buffer)
            if buf_and_length.bytes_received > 0:
                return
            # TEMP (field observation): logged at INFO instead of DEBUG so timeout/retry
            # events are visible at the normal startup log level.  Revert to DEBUG after.
            if retries_left > 0:
                logging.info(b'received %d bytes response to %s, %d retries left.' % (buf_and_length.bytes_received, message, retries_left),
                             'kdevice:device_send_receive')
            else:
                logging.info(b'timeout waiting for response to "%s".' % (message,), 'kdevice:device_send_receive')

    @staticmethod
    async def read_network_client(lines) -> bytes | None:
        try:
            data = await lines.readline()
            if data == b'':          # EOF — peer closed
                return None          # callers already treat None as disconnect
            return data.strip()
        except ValueError:  # line exceeded LineReader's limit; drop the client.
            logging.warning('client sent an overlong line, disconnecting', 'kdevice:read_network_client')
            return None
        # except ConnectionResetError as cre:  # micropython does not support ConnectionResetError
        #    logging.warning(f'ConnectionResetError in read_network_client: {str(cre)}', 'read_network_client')
        except Exception as exc:
            logging.exception(f'exception in read_network_client: {str(exc)}',
                              'kdevice:read_network_client', exc_info=exc)
        return None
