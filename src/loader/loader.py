#!/bin/env python3
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

import os
import sys

import serial
from serial.tools.list_ports import comports
from pyboard import Pyboard, PyboardError
BAUD_RATE = 115200

SRC_DIR = '../kpa500-remote/'
FILES_LIST = [
    'content/',
    'data/',
    'http_server.py',
    'kdevice.py',
    'kat500.py',
    'kpa500.py',
    'main.py',
    'micro_logging.py',
    'utils.py',
    'morse_code.py',
    'picow_network.py',
    'serialport.py',
    'content/favicon.ico',
    'content/files.html',
    'content/kat500.html',
    'content/kpa500.html',
    'content/setup.html',
    'data/config.json',
]


def get_ports_list():
    ports = comports()
    ports_list = []
    for port in ports:
        ports_list.append(port.device)
    return sorted(ports_list)


# noinspection PyUnusedLocal
def put_file_progress_callback(bytes_so_far, bytes_total):
    print('.', end='')


def put_file(filename, target):
    src_file_name = SRC_DIR + filename
    if filename[-1:] == '/':
        filename = filename[:-1]
        try:
            target.fs_mkdir(filename)
            print(f'created directory {filename}')
        except PyboardError as exc:
            if 'EEXIST' not in str(exc):
                print(f'failed to create directory {filename}')
                print(type(exc), exc)
    else:
        try:
            os.stat(src_file_name)
            print(f'sending file {filename} ', end='')
            target.fs_put(src_file_name, filename, progress_callback=put_file_progress_callback)
            print()
        except OSError:
            print(f'cannot find source file {src_file_name}')


class BytesConcatenator(object):
    """
    this is used to collect data from pyboard functions that otherwise do not return data.
    """

    def __init__(self):
        self.data = bytearray()

    def write_bytes(self, b):
        b = b.replace(b"\x04", b"")
        self.data.extend(b)

    def __str__(self):
        stuff = self.data.decode('utf-8').replace('\r', '')
        return stuff


def loader_ls(target, src='/'):
    files_found = []
    files_data = BytesConcatenator()
    cmd = (
        "import uos\nfor f in uos.ilistdir(%s):\n"
        " print('{}{}'.format(f[0],'/'if f[1]&0x4000 else ''))"
        % (("'%s'" % src) if src else "")
    )
    target.exec_(cmd, data_consumer=files_data.write_bytes)
    files = str(files_data).split('\n')
    for phile in files:
        if len(phile) > 0:
            if phile.endswith('/'):
                children = loader_ls(target, phile)
                for child in children:
                    files_found.append(f'{phile}{child}')
            else:
                files_found.append(phile)
    return files_found


def load_device(port):
    try:
        target = Pyboard(port, BAUD_RATE)
    except PyboardError:
        print(f'cannot connect to device {port}')
        sys.exit(1)
    target.enter_raw_repl()

    # clean up files that do not belong here.
    existing_files = loader_ls(target)
    for existing_file in existing_files:
        if existing_file not in FILES_LIST:
            if existing_file[:-1] == '/':
                print(f'removing directory {existing_file[:-1]}')
                target.fs_rm(existing_file[:-1])
            else:
                print(f'removing file {existing_file}')
                target.fs_rm(existing_file)

    # now add the files that do belong here.
    for file in FILES_LIST:
        put_file(file, target)
    target.exit_raw_repl()
    target.close()

    # this is a hack that allows the Pico-W to be restarted by this script.
    # it exits the REPL by sending a control-D.
    # why this functionality is not the Pyboard module is a good question.
    with serial.Serial(port=port,
                       baudrate=BAUD_RATE,
                       parity=serial.PARITY_NONE,
                       bytesize=serial.EIGHTBITS,
                       stopbits=serial.STOPBITS_ONE,
                       timeout=1) as pyboard_port:
        pyboard_port.write(b'\x04')
        print('\nDevice should restart.')
        # now just echo the Pico-W output to the console.
        while True:
            try:
                b = pyboard_port.read(1)
                sys.stdout.write(b.decode())
            except serial.SerialException:
                print(f'\n\nLost connection to device on {port}.')
                break


def main():
    if len(sys.argv) == 2:
        picow_port = sys.argv[1]
    else:
        print('Disconnect the Pico-W if it is connected.')
        input('(press enter to continue...)')
        ports_1 = get_ports_list()
        print('Detected serial ports: ' + ' '.join(ports_1))
        print('\nConnect the Pico-W to USB port. Wait for the USB connected sound.')
        input('(press enter to continue...)')
        ports_2 = get_ports_list()
        print('Detected serial ports: ' + ' '.join(ports_2))

        picow_port = None
        for port in ports_2:
            if port not in ports_1:
                picow_port = port
                break

    if picow_port is None:
        print('Could not identify Pico-W communications port.  Exiting.')
        sys.exit(1)

    print(f'\nAttempting to load device on port {picow_port}')
    load_device(picow_port)


if __name__ == "__main__":
    main()
