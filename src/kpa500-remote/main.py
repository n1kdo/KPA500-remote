#
# main.py -- this is the web server for the Raspberry Pi Pico W Web IOT thing.
#
__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2022, J. B. Otterson N1KDO.'

#
# Copyright 2022, J. B. Otterson N1KDO.
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

import gc
import json
import os
import re
import sys
import time

import ntp
from kpa500 import ClientData, KPA500
from serialport import SerialPort

upython = sys.implementation.name == 'micropython'

if upython:
    import machine
    import network
    import uasyncio as asyncio
    from uasyncio import TimeoutError
else:
    import asyncio
    from asyncio.exceptions import TimeoutError

    class Machine(object):
        """
        fake micropython stuff
        """

        @staticmethod
        def soft_reset():
            print('Machine.soft_reset()')

        class Pin(object):
            OUT = 1
            IN = 0
            PULL_UP = 0

            def __init__(self, name, options=0, value=0):
                self.name = name
                self.options = options
                self.state = value
                pass

            def on(self):
                self.state = 1
                pass

            def off(self):
                self.state = 0

            def value(self):
                return self.state

    machine = Machine()


if upython:
    onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
    onboard.on()
    blinky = machine.Pin(2, machine.Pin.OUT, value=0)  # status LED
    button = machine.Pin(3, machine.Pin.IN, machine.Pin.PULL_UP)


BUFFER_SIZE = 4096
CONFIG_FILE = 'data/config.json'
CONTENT_DIR = 'content/'
CT_TEXT_TEXT = 'text/text'
CT_TEXT_HTML = 'text/html'
CT_APP_JSON = 'application/json'
CT_APP_WWW_FORM = 'application/x-www-form-urlencoded'
CT_MULTIPART_FORM = 'multipart/form-data'
DANGER_ZONE_FILE_NAMES = (
    'config.html',
    'files.html',
    'kpa500.html',
)
# noinspection SpellCheckingInspection
DEFAULT_SECRET = 'elecraft'
DEFAULT_SSID = 'kpa500'
DEFAULT_TCP_PORT = 4626
DEFAULT_WEB_PORT = 80
FILE_EXTENSION_TO_CONTENT_TYPE_MAP = {
    'gif': 'image/gif',
    'html': CT_TEXT_HTML,
    'ico': 'image/vnd.microsoft.icon',
    'json': CT_APP_JSON,
    'jpeg': 'image/jpeg',
    'jpg': 'image/jpeg',
    'png': 'image/png',
    'txt': CT_TEXT_TEXT,
    '*': 'application/octet-stream',
}
HYPHENS = '--'
HTTP_STATUS_TEXT = {
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    204: 'No Content',
    301: 'Moved Permanently',
    302: 'Moved Temporarily',
    304: 'Not Modified',
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    409: 'Conflict',
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
}
MORSE_PERIOD = 15  # x 10 to MS: the speed of the morse code is set by the dit length of 150 ms.
MORSE_DIT = MORSE_PERIOD
MORSE_ESP = MORSE_DIT  # inter-element space
MORSE_DAH = 3 * MORSE_PERIOD
MORSE_LSP = 5 * MORSE_PERIOD  # more space between letters
MORSE_PATTERNS = {  # sparse to save space
    ' ': (0, 0, 0, 0, 0),  # 5 element spaces then a letter space = 10 element pause  # space is 0x20 ascii
    '0': (MORSE_DAH, MORSE_DAH, MORSE_DAH, MORSE_DAH, MORSE_DAH),  # 0 is 0x30 ascii
    '1': (MORSE_DIT, MORSE_DAH, MORSE_DAH, MORSE_DAH, MORSE_DAH),
    '2': (MORSE_DIT, MORSE_DIT, MORSE_DAH, MORSE_DAH, MORSE_DAH),
    '3': (MORSE_DIT, MORSE_DIT, MORSE_DIT, MORSE_DAH, MORSE_DAH),
    '4': (MORSE_DIT, MORSE_DIT, MORSE_DIT, MORSE_DIT, MORSE_DAH),
    '5': (MORSE_DIT, MORSE_DIT, MORSE_DIT, MORSE_DIT, MORSE_DIT),
    '6': (MORSE_DAH, MORSE_DIT, MORSE_DIT, MORSE_DIT, MORSE_DIT),
    '7': (MORSE_DAH, MORSE_DAH, MORSE_DIT, MORSE_DIT, MORSE_DIT),
    '8': (MORSE_DAH, MORSE_DAH, MORSE_DAH, MORSE_DIT, MORSE_DIT),
    '9': (MORSE_DAH, MORSE_DAH, MORSE_DAH, MORSE_DAH, MORSE_DIT),
    'A': (MORSE_DIT, MORSE_DAH),                                    # 'A' is 0x41 ascii
    #  'C': (MORSE_DAH, MORSE_DIT, MORSE_DAH, MORSE_DIT),
    'E': (MORSE_DIT, ),
    #  'I': (MORSE_DIT, MORSE_DIT),
    #  'S': (MORSE_DIT, MORSE_DIT, MORSE_DIT),
    'R': (MORSE_DIT, MORSE_DAH, MORSE_DIT),
    #  'H': (MORSE_DIT, MORSE_DIT, MORSE_DIT, MORSE_DIT),
    #  'O': (MORSE_DAH, MORSE_DAH, MORSE_DAH),
    #  'N': (MORSE_DAH, MORSE_DIT),
    #  'D': (MORSE_DAH, MORSE_DIT, MORSE_DIT),
    #  'B': (MORSE_DAH, MORSE_DIT, MORSE_DIT, MORSE_DIT),
}
MP_START_BOUND = 1
MP_HEADERS = 2
MP_DATA = 3
MP_END_BOUND = 4

# globals...
morse_message = ''
restart = False
port = None
username = ''
password = ''
kpa500 = KPA500()


def get_timestamp(tt=None):
    if tt is None:
        tt = time.gmtime()
    return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}Z'.format(tt[0], tt[1], tt[2], tt[3], tt[4], tt[5])


def get_iso_8601_timestamp(tt=None):
    if tt is None:
        tt = time.gmtime()
    return '{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}+00:00'.format(tt[0], tt[1], tt[2], tt[3], tt[4], tt[5])


def read_config():
    config = {}
    try:
        with open(CONFIG_FILE, 'r') as config_file:
            config = json.load(config_file)
    except Exception as ex:
        print('failed to load configuration!', type(ex), ex)
    return config


def save_config(config):
    with open(CONFIG_FILE, 'w') as config_file:
        json.dump(config, config_file)


def safe_int(s, default=-1):
    if type(s) == int:
        return s
    else:
        return int(s) if s.isdigit() else default


def milliseconds():
    if upython:
        return time.ticks_ms()
    else:
        return int(time.time() * 1000)


def valid_filename(filename):
    if filename is None:
        return False
    match = re.match('^[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?.[a-zA-Z0-9_-]+$', filename)
    if match is None:
        return False
    if match.group(0) != filename:
        return False
    extension = filename.split('.')[-1].lower()
    if FILE_EXTENSION_TO_CONTENT_TYPE_MAP.get(extension) is None:
        return False
    return True


def serve_content(writer, filename):
    filename = CONTENT_DIR + filename
    try:
        content_length = safe_int(os.stat(filename)[6], -1)
    except OSError:
        content_length = -1
    if content_length < 0:
        response = b'<html><body><p>404.  Means &quot;no got&quot;.</p></body></html>'
        http_status = 404
        return send_simple_response(writer, http_status, CT_TEXT_HTML, response), http_status
    else:
        extension = filename.split('.')[-1]
        content_type = FILE_EXTENSION_TO_CONTENT_TYPE_MAP.get(extension)
        if content_type is None:
            content_type = FILE_EXTENSION_TO_CONTENT_TYPE_MAP.get('*')
        http_status = 200
        start_response(writer, 200, content_type, content_length)
        try:
            with open(filename, 'rb', BUFFER_SIZE) as infile:
                while True:
                    buffer = infile.read(BUFFER_SIZE)
                    writer.write(buffer)
                    if len(buffer) < BUFFER_SIZE:
                        break
        except Exception as e:
            print(type(e), e)
        return content_length, http_status


def start_response(writer, http_status=200, content_type=None, response_size=0, extra_headers=None):
    status_text = HTTP_STATUS_TEXT.get(http_status) or 'Confused'
    protocol = 'HTTP/1.0'
    writer.write('{} {} {}\r\n'.format(protocol, http_status, status_text).encode('utf-8'))
    if content_type is not None and len(content_type) > 0:
        writer.write('Content-type: {}; charset=UTF-8\r\n'.format(content_type).encode('utf-8'))
    if response_size > 0:
        writer.write('Content-length: {}\r\n'.format(response_size).encode('utf-8'))
    if extra_headers is not None:
        for header in extra_headers:
            writer.write('{}\r\n'.format(header).encode('utf-8'))
    writer.write(b'\r\n')


def send_simple_response(writer, http_status=200, content_type=None, response=None, extra_headers=None):
    content_length = len(response) if response else 0
    start_response(writer, http_status, content_type, content_length, extra_headers)
    if response is not None and len(response) > 0:
        writer.write(response)
    return content_length


def connect_to_network(config):
    global morse_message

    ssid = config.get('SSID') or ''
    if len(ssid) == 0 or len(ssid) > 64:
        ssid = DEFAULT_SSID
    secret = config.get('secret') or ''
    if len(secret) > 64:
        secret = ''
    access_point_mode = config.get('ap_mode') or False

    if access_point_mode:
        print('Starting setup WLAN...')
        wlan = network.WLAN(network.AP_IF)
        wlan.active(False)
        wlan.config(pm=0xa11140)  # disable power save, this is a server.

        hostname = config.get('hostname')
        if hostname is not None:
            try:
                wlan.config(hostname=hostname)
            except ValueError:
                print(f'hostname is still not supported on Pico W')

        # wlan.ifconfig(('10.0.0.1', '255.255.255.0', '0.0.0.0', '0.0.0.0'))

        """
        #define CYW43_AUTH_OPEN (0)                     ///< No authorisation required (open)
        #define CYW43_AUTH_WPA_TKIP_PSK   (0x00200002)  ///< WPA authorisation
        #define CYW43_AUTH_WPA2_AES_PSK   (0x00400004)  ///< WPA2 authorisation (preferred)
        #define CYW43_AUTH_WPA2_MIXED_PSK (0x00400006)  ///< WPA2/WPA mixed authorisation
        """
        ssid = DEFAULT_SSID
        secret = DEFAULT_SECRET
        if len(secret) == 0:
            security = 0
        else:
            security = 0x00400004  # CYW43_AUTH_WPA2_AES_PSK
        wlan.config(ssid=ssid, key=secret, security=security)
        wlan.active(True)
        print(wlan.active())
        print('ssid={}'.format(wlan.config('ssid')))
    else:
        print('Connecting to WLAN...')
        wlan = network.WLAN(network.STA_IF)
        wlan.config(pm=0xa11140)  # disable power save, this is a server.

        hostname = config.get('hostname')
        if hostname is not None:
            try:
                wlan.config(hostname=hostname)
            except ValueError:
                print(f'hostname is still not supported on Pico W')

        is_dhcp = config.get('dhcp') or True
        if not is_dhcp:
            ip_address = config.get('ip_address')
            netmask = config.get('netmask')
            gateway = config.get('gateway')
            dns_server = config.get('dns_server')
            if ip_address is not None and netmask is not None and gateway is not None and dns_server is not None:
                print('setting up static IP')
                wlan.ifconfig((ip_address, netmask, gateway, dns_server))
            else:
                print('cannot use static IP, data is missing, configuring network with DHCP')
                wlan.ifconfig('dhcp')
        else:
            print('configuring network with DHCP')
            # wlan.ifconfig('dhcp')  #  this does not work.  network does not come up.  no errors, either.

        wlan.active(True)
        wlan.connect(ssid, secret)
        max_wait = 10
        while max_wait > 0:
            status = wlan.status()
            if status < 0 or status >= 3:
                break
            max_wait -= 1
            print('Waiting for connection to come up, status={}'.format(status))
            time.sleep(1)
        if wlan.status() != network.STAT_GOT_IP:
            morse_message = 'ERR'
            # return None
            raise RuntimeError('Network connection failed')

    status = wlan.ifconfig()
    ip_address = status[0]
    morse_message = 'A  {}  '.format(ip_address) if access_point_mode else '{} '.format(ip_address)
    morse_message = morse_message.replace('.', ' ')
    print(morse_message)
    return ip_address


def unpack_args(s):
    args_dict = {}
    if s is not None:
        args_list = s.split('&')
        for arg in args_list:
            arg_parts = arg.split('=')
            if len(arg_parts) == 2:
                args_dict[arg_parts[0]] = arg_parts[1]
    return args_dict


async def read_network_client(reader):
    try:
        data = await reader.readline()
        return data.decode().strip()
    except ConnectionResetError as cre:
        print(f'ConnectionResetError in read_network_client: {str(cre)}')
    except Exception as ex:
        print(ex)
        print(f'exception in read_network_client: {str(ex)}')
    return None


async def serve_network_client(reader, writer):
    """
    this provides KPA500-Remote compatible control.
    """
    verbosity = 1
    t0 = milliseconds()
    extra = writer.get_extra_info('peername')
    client_name = f'{extra[0]}:{extra[1]}'
    client_data = ClientData(client_name)
    client_data.update_list.extend((7, 16, 6, 0, 1, 2, 3, 4, 8, 5, 9, 10, 11, 12, 13, 14, 15, 17, 18))  # items to send.
    kpa500.network_clients.append(client_data)
    if verbosity > 2:
        print('network client connected from {}'.format(extra[0]))

    try:
        while client_data.connected:
            try:
                message = await asyncio.wait_for(read_network_client(reader), 0.05)
                timed_out = False
            except TimeoutError as e:
                message = None
                timed_out = True
            if message is not None and not timed_out:
                client_data.last_receive = milliseconds()
                if len(message) == 0:  # keepalive?
                    if verbosity > 3:
                        print(f'{get_timestamp()}: RECEIVED keepalive FROM client {client_name}')
                elif message.startswith('server::login::'):
                    up_list = message[15:].split('::')
                    if up_list[0] != username:
                        response = b'server::login::invalid::Invalid username provided. '\
                                   b'Remote control will not be allowed.\n'
                    elif up_list[1] != password:
                        response = b'server::login::invalid::Invalid password provided. '\
                                   b'Remote control will not be allowed.\n'
                    else:
                        response = b'server::login::valid\n'
                        client_data.authorized = True
                    writer.write(response)
                    client_data.last_send = milliseconds
                    if verbosity > 3:
                        print(f'sending "{response.decode().strip()}"')
                else:
                    if client_data.authorized:
                        # noinspection SpellCheckingInspection
                        if message.startswith('amp::button::CLEAR::'):
                            kpa500.enqueue_command(b'^FLC;')
                        elif message.startswith('amp::button::OPER::'):
                            value = message[19:]
                            if value == '1':
                                command = b'^OS1;^OS;'
                            else:
                                command = b'^OS0;^OS;'
                            kpa500.enqueue_command(command)
                        elif message.startswith('amp::button::STBY::'):
                            value = message[19:]
                            if value == '0':
                                command = b'^OS1;^OS;'
                            else:
                                command = b'^OS0;^OS;'
                            kpa500.enqueue_command(command)
                        elif message.startswith('amp::button::PWR::'):
                            # print(message)
                            value = message[18:]
                            if value == '1':
                                command = b'^ON1;'
                            else:
                                command = b'^ON0;'
                            kpa500.enqueue_command(command)

                        elif message.startswith('amp::button::SPKR::'):
                            value = message[19:]
                            if value == '1':
                                command = b'^SP1;'
                            else:
                                command = b'^SP0;'
                            kpa500.enqueue_command(command)
                        elif message.startswith('amp::dropdown::Band::'):
                            value = message[21:]
                            band_number = kpa500.band_label_to_number(value)
                            if band_number is not None:
                                command = f'^BN{band_number:02d};'.encode()
                                kpa500.enqueue_command(command)
                        elif message.startswith('amp::slider::Fan Speed::'):
                            value = message[24:]
                            command = f'^FC{value};^FC;'.encode()
                            kpa500.enqueue_command(command)
                        else:
                            print(f'unhandled message "{message}"')
            else:  # response was None
                if not timed_out:
                    print('response was None')
                    client_data.connected = False

            # send any outstanding data back...
            if len(client_data.update_list) > 0:
                index = client_data.update_list.pop(0)
                writer.write(kpa500.key_names[index])
                payload = f'::{kpa500.kpa500_data[index]}\n'.encode()
                writer.write(payload)
                await writer.drain()
                client_data.last_send = milliseconds()
                if verbosity > 3:
                    print(f'sent "{kpa500.key_names[index].decode()}{payload.decode().strip()}"')

            receive_delta = milliseconds() - client_data.last_receive
            send_delta = milliseconds() - client_data.last_send

            if send_delta > 15000:
                writer.write(b'\n')
                await writer.drain()
                client_data.last_send = milliseconds()
                if verbosity > 3:
                    print(f'{get_timestamp()}: SENT keepalive TO client {client_name}')
            if receive_delta > 300000:  # 10 minutes no activity timeout.
                if verbosity > 2:
                    print(f'client {client_name} no activity timeout {receive_delta/1000:6.1f}, closing connection')
                client_data.connected = False

            gc.collect()

        # connection closing
        print(f'connection from {client_data.client_name} closing...')
        writer.close()
        await writer.wait_closed()

    except Exception as ex:
        print('exception in serve_network_client:', type(ex), ex)
        raise ex
    finally:
        print(f'client {client_data.client_name} disconnected')
        found_network_client = None
        for network_client in kpa500.network_clients:
            if network_client.client_name == client_data.client_name:
                found_network_client = network_client
                break
        if found_network_client is not None:
            kpa500.network_clients.remove(found_network_client)
            print(f'network client removed {client_name}')

    tc = milliseconds()
    print('network client disconnected, elapsed time {:6.3f} seconds'.format((tc - t0) / 1000.0))


async def serve_http_client(reader, writer):
    global restart
    verbosity = 3
    t0 = milliseconds()
    http_status = 418  # can only make tea, sorry.
    bytes_sent = 0
    partner = writer.get_extra_info('peername')[0]
    if verbosity >= 4:
        print('\nweb client connected from {}'.format(partner))
    request_line = await reader.readline()
    request = request_line.decode().strip()
    if verbosity >= 4:
        print(request)
    pieces = request.split(' ')
    if len(pieces) != 3:  # does the http request line look approximately correct?
        http_status = 400
        response = b'Bad Request !=3'
        bytes_sent = send_simple_response(writer, http_status, CT_TEXT_HTML, response)
    else:
        verb = pieces[0]
        target = pieces[1]
        protocol = pieces[2]
        # should validate protocol here...
        if '?' in target:
            pieces = target.split('?')
            target = pieces[0]
            query_args = pieces[1]
        else:
            query_args = ''
        if verb not in ['GET', 'POST']:
            http_status = 400
            response = b'<html><body><p>only GET and POST are supported</p></body></html>'
            bytes_sent = send_simple_response(writer, http_status, CT_TEXT_HTML, response)
        elif protocol not in ['HTTP/1.0', 'HTTP/1.1']:
            http_status = 400
            response = b'that protocol is not supported'
            bytes_sent = send_simple_response(writer, http_status, CT_TEXT_HTML, response)
        else:
            # get HTTP request headers
            request_content_length = 0
            request_content_type = ''
            while True:
                header = await reader.readline()
                if len(header) == 0:
                    # empty header line, eof?
                    break
                if header == b'\r\n':
                    # blank line at end of headers
                    break
                else:
                    # process headers.  look for those we are interested in.
                    # print(header)
                    parts = header.decode().strip().split(':', 1)
                    if parts[0] == 'Content-Length':
                        request_content_length = int(parts[1].strip())
                    elif parts[0] == 'Content-Type':
                        request_content_type = parts[1].strip()

            args = {}
            if verb == 'GET':
                args = unpack_args(query_args)
            elif verb == 'POST':
                if request_content_length > 0:
                    if request_content_type == CT_APP_WWW_FORM:
                        data = await reader.read(request_content_length)
                        args = unpack_args(data.decode())
                    elif request_content_type == CT_APP_JSON:
                        data = await reader.read(request_content_length)
                        args = json.loads(data.decode())
                    # else:
                    #    print('warning: unhandled content_type {}'.format(request_content_type))
                    #    print('request_content_length={}'.format(request_content_length))
            else:  # bad request
                http_status = 400
                response = b'only GET and POST are supported'
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)

            if target == '/':
                http_status = 301
                bytes_sent = send_simple_response(writer, http_status, None, None, ['Location: /kpa500.html'])
            elif target == '/api/config':
                if verb == 'GET':
                    payload = read_config()
                    # payload.pop('secret')  # do not return the secret
                    response = json.dumps(payload).encode('utf-8')
                    http_status = 200
                    bytes_sent = send_simple_response(writer, http_status, CT_APP_JSON, response)
                elif verb == 'POST':
                    config = read_config()
                    dirty = False
                    errors = False
                    tcp_port = args.get('tcp_port')
                    if tcp_port is not None:
                        tcp_port_int = safe_int(tcp_port, -2)
                        if 0 <= tcp_port_int <= 65535:
                            config['tcp_port'] = tcp_port
                            dirty = True
                        else:
                            errors = True
                    web_port = args.get('web_port')
                    if web_port is not None:
                        web_port_int = safe_int(web_port, -2)
                        if 0 <= web_port_int <= 65535:
                            config['web_port'] = web_port
                            dirty = True
                        else:
                            errors = True
                    ssid = args.get('SSID')
                    if ssid is not None:
                        if 0 < len(ssid) < 64:
                            config['SSID'] = ssid
                            dirty = True
                        else:
                            errors = True
                    secret = args.get('secret')
                    if secret is not None:
                        if 8 <= len(secret) < 32:
                            config['secret'] = secret
                            dirty = True
                        else:
                            errors = True
                    username = args.get('username')
                    if username is not None:
                        if 1 <= len(username) <= 16:
                            config['username'] = username
                            dirty = True
                        else:
                            errors = True
                    password = args.get('password')
                    if password is not None:
                        if 1 <= len(password) <+ 16:
                            config['password'] = password
                            dirty = True
                        else:
                            errors = True
                    ap_mode_arg = args.get('ap_mode')
                    if ap_mode_arg is not None:
                        ap_mode = True if ap_mode_arg == '1' else False
                        config['ap_mode'] = ap_mode
                        dirty = True
                    dhcp_arg = args.get('dhcp')
                    if dhcp_arg is not None:
                        dhcp = True if dhcp_arg == 1 else False
                        config['dhcp'] = dhcp
                        dirty = True
                    ip_address = args.get('ip_address')
                    if ip_address is not None:
                        config['ip_address'] = ip_address
                        dirty = True
                    netmask = args.get('netmask')
                    if netmask is not None:
                        config['netmask'] = netmask
                        dirty = True
                    gateway = args.get('gateway')
                    if gateway is not None:
                        config['gateway'] = gateway
                        dirty = True
                    dns_server = args.get('dns_server')
                    if dns_server is not None:
                        config['dns_server'] = dns_server
                        dirty = True
                    if not errors:
                        if dirty:
                            save_config(config)
                        response = b'ok\r\n'
                        http_status = 200
                        bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
                    else:
                        response = b'parameter out of range\r\n'
                        http_status = 400
                        bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)

            elif target == '/api/get_files':
                if verb == 'GET':
                    payload = os.listdir(CONTENT_DIR)
                    response = json.dumps(payload).encode('utf-8')
                    http_status = 200
                    bytes_sent = send_simple_response(writer, http_status, CT_APP_JSON, response)
            elif target == '/api/upload_file':
                if verb == 'POST':
                    boundary = None
                    if ';' in request_content_type:
                        pieces = request_content_type.split(';')
                        request_content_type = pieces[0]
                        boundary = pieces[1].strip()
                        if boundary.startswith('boundary='):
                            boundary = boundary[9:]
                    if request_content_type != CT_MULTIPART_FORM or boundary is None:
                        response = b'multipart boundary or content type error'
                        http_status = 400
                    else:
                        response = b'unhandled problem'
                        http_status = 500
                        remaining_content_length = request_content_length
                        start_boundary = HYPHENS + boundary
                        end_boundary = start_boundary + HYPHENS
                        state = MP_START_BOUND
                        filename = None
                        output_file = None
                        writing_file = False
                        more_bytes = True
                        leftover_bytes = []
                        while more_bytes:
                            # print('waiting for read')
                            buffer = await reader.read(BUFFER_SIZE)
                            # print('read {} bytes of max {}'.format(len(buffer), BUFFER_SIZE))
                            remaining_content_length -= len(buffer)
                            # print('remaining content length {}'.format(remaining_content_length))
                            if remaining_content_length == 0:  # < BUFFER_SIZE:
                                more_bytes = False
                            if len(leftover_bytes) != 0:
                                buffer = leftover_bytes + buffer
                                leftover_bytes = []
                            start = 0
                            while start < len(buffer):
                                if state == MP_DATA:
                                    if not output_file:
                                        output_file = open(CONTENT_DIR + 'uploaded_' + filename, 'wb')
                                        writing_file = True
                                    end = len(buffer)
                                    for i in range(start, len(buffer) - 3):
                                        if buffer[i] == 13 and buffer[i + 1] == 10 and buffer[i + 2] == 45 and \
                                                buffer[i + 3] == 45:
                                            end = i
                                            writing_file = False
                                            break
                                    if end == BUFFER_SIZE:
                                        if buffer[-1] == 13:
                                            leftover_bytes = buffer[-1:]
                                            buffer = buffer[:-1]
                                            end -= 1
                                        elif buffer[-2] == 13 and buffer[-1] == 10:
                                            leftover_bytes = buffer[-2:]
                                            buffer = buffer[:-2]
                                            end -= 2
                                        elif buffer[-3] == 13 and buffer[-2] == 10 and buffer[-1] == 45:
                                            leftover_bytes = buffer[-3:]
                                            buffer = buffer[:-3]
                                            end -= 3
                                    # print('writing buffer[{}:{}] buffer size={}'.format(start, end, BUFFER_SIZE))
                                    output_file.write(buffer[start:end])
                                    if not writing_file:
                                        # print('closing file')
                                        state = MP_END_BOUND
                                        output_file.close()
                                        output_file = None
                                        response = 'Uploaded {} successfully'.format(filename).encode('utf-8')
                                        http_status = 201
                                    start = end + 2
                                else:  # must be reading headers or boundary
                                    line = ''
                                    for i in range(start, len(buffer) - 1):
                                        if buffer[i] == 13 and buffer[i + 1] == 10:
                                            line = buffer[start:i].decode('utf-8')
                                            start = i + 2
                                            break
                                    if state == MP_START_BOUND:
                                        if line == start_boundary:
                                            state = MP_HEADERS
                                        else:
                                            print('expecting start boundary, got ' + line)
                                    elif state == MP_HEADERS:
                                        if len(line) == 0:
                                            state = MP_DATA
                                        elif line.startswith('Content-Disposition:'):
                                            pieces = line.split(';')
                                            fn = pieces[2].strip()
                                            if fn.startswith('filename="'):
                                                filename = fn[10:-1]
                                                if not valid_filename(filename):
                                                    response = b'bad filename'
                                                    http_status = 500
                                                    more_bytes = False
                                                    start = len(buffer)
                                        # else:
                                        #     print('processing headers, got ' + line)
                                    elif state == MP_END_BOUND:
                                        if line == end_boundary:
                                            state = MP_START_BOUND
                                        else:
                                            print('expecting end boundary, got ' + line)
                                    else:
                                        http_status = 500
                                        response = 'unmanaged state {}'.format(state).encode('utf-8')
                    bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/remove_file':
                filename = args.get('filename')
                if valid_filename(filename) and filename not in DANGER_ZONE_FILE_NAMES:
                    filename = CONTENT_DIR + filename
                    try:
                        os.remove(filename)
                        http_status = 200
                        response = b'removed\r\n'
                    except OSError as ose:
                        http_status = 409
                        response = str(ose).encode('utf-8')
                else:
                    http_status = 409
                    response = b'bad file name\r\n'
                bytes_sent = send_simple_response(writer, http_status, CT_APP_JSON, response)
            elif target == '/api/rename_file':
                filename = args.get('filename')
                newname = args.get('newname')
                if valid_filename(filename) and valid_filename(newname):
                    filename = CONTENT_DIR + filename
                    newname = CONTENT_DIR + newname
                    try:
                        os.remove(newname)
                    except OSError:
                        pass  # swallow exception.
                    try:
                        os.rename(filename, newname)
                        http_status = 200
                        response = b'renamed\r\n'
                    except Exception as ose:
                        http_status = 409
                        response = str(ose).encode('utf-8')
                else:
                    http_status = 409
                    response = b'bad file name'
                bytes_sent = send_simple_response(writer, http_status, CT_APP_JSON, response)
            elif target == '/api/restart' and upython:
                restart = True
                response = b'ok\r\n'
                http_status = 200
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/clear_fault':
                kpa500.enqueue_command(b'^FLC;')
                response = b'ok\r\n'
                http_status = 200
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/set_band':
                band_name = args.get('band')
                band_number = kpa500.band_label_to_number(band_name)
                if band_number is not None:
                    command = f'^BN{band_number:02d};'.encode()
                    kpa500.enqueue_command(command)
                    response = b'ok\r\n'
                    http_status = 200
                else:
                    response = b'bad band name parameter\r\n'
                    http_status = 400
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/set_fan_speed':
                speed = safe_int(args.get('speed', -1))
                if 0 <= speed <= 6:
                    command = f'^FC{speed};^FC;'.encode()
                    kpa500.enqueue_command(command)
                    response = b'ok\r\n'
                    http_status = 200
                else:
                    response = b'bad fan speed parameter\r\n'
                    http_status = 400
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/set_operate':
                state = args.get('state')
                if state == '0' or state == '1':
                    command = f'^OS{state};^OS;'.encode()
                    kpa500.enqueue_command(command)
                    response = b'ok\r\n'
                    http_status = 200
                else:
                    response = b'bad state parameter\r\n'
                    http_status = 400
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/set_power':
                state = args.get('state')
                if state == '0' or state == '1':
                    command = f'^ON{state};'.encode()
                    kpa500.enqueue_command(command)
                    response = b'ok\r\n'
                    http_status = 200
                else:
                    response = b'bad state parameter\r\n'
                    http_status = 400
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/set_speaker_alarm':
                state = args.get('state')
                if state == '0' or state == '1':
                    command = f'^SP{state};'.encode()
                    kpa500.enqueue_command(command)
                    response = b'ok\r\n'
                    http_status = 200
                else:
                    response = b'bad state parameter\r\n'
                    http_status = 400
                bytes_sent = send_simple_response(writer, http_status, CT_TEXT_TEXT, response)
            elif target == '/api/status':
                payload = {'kpa500_data': kpa500.kpa500_data}
                response = json.dumps(payload).encode('utf-8')
                http_status = 200
                bytes_sent = send_simple_response(writer, http_status, CT_APP_JSON, response)
            else:
                content_file = target[1:] if target[0] == '/' else target
                bytes_sent, http_status = serve_content(writer, content_file)

    await writer.drain()
    writer.close()
    await writer.wait_closed()
    elapsed = milliseconds() - t0
    if http_status == 200:
        if verbosity > 2:
            print('{} {} {} {} {} ms'.format(partner, request, http_status, bytes_sent, elapsed))
    else:
        if verbosity >= 1:
            print('{} {} {} {} {} ms'.format(partner, request, http_status, bytes_sent, elapsed))
    gc.collect()


async def morse_sender():
    while True:
        msg = morse_message  # using global...
        for morse_letter in msg:
            blink_pattern = MORSE_PATTERNS.get(morse_letter)
            if blink_pattern is None:
                print('Warning: no pattern for letter {}'.format(morse_letter))
                blink_pattern = MORSE_PATTERNS.get(' ')
            blink_list = [elem for elem in blink_pattern]
            while len(blink_list) > 0:
                t = blink_list.pop(0)
                if t > 0:
                    # blink time is in milliseconds!, but data is in 10 msec
                    blinky.on()
                    await asyncio.sleep(t/100)
                    blinky.off()
                await asyncio.sleep(MORSE_ESP / 100 if len(blink_list) > 0 else MORSE_LSP / 100)


class BufferAndLength:
    def __init__(self, buffer):
        self.buffer = buffer
        self.bytes_received = 0

    def data(self):
        return self.buffer[:self.bytes_received]


async def kpa500_send_receive(amp_port, message, bl, timeout=0.05):
    # should the read buffer be flushed? can only read to drain
    while len(amp_port.read()) > 0:
        pass
    amp_port.write(message)
    amp_port.flush()
    await asyncio.sleep(timeout)
    bl.bytes_received = amp_port.readinto(bl.buffer)


async def kpa500_server(amp_serial_port, verbosity=3):
    """
    this manages the connection to the physical amplifier
    :param amp_serial_port: SerialPort object
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
            await kpa500_send_receive(amp_serial_port, b';', bl)
            # connected will return a ';' here
            if bl.bytes_received != 1 or bl.buffer[0] != 59:
                kpa500.update_kpa500_data(6, 'NO AMP')
            else:
                amp_state = 1
                if verbosity > 3:
                    print('amp state 0-->1')
        elif amp_state == 1:  # apparently connected
            # ask if it is turned on.
            await kpa500_send_receive(amp_serial_port, b'^ON;', bl)  # hi there.
            # is b'^ON1;' when amp is on.
            # is b'^ON;' when amp is off
            # is b'' when amp is not found.
            if bl.bytes_received == 0:
                amp_state = 0
                kpa500.update_kpa500_data(4, '0')  # not powered
                kpa500.update_kpa500_data(6, 'NO AMP')
                if verbosity > 3:
                    print('1: no response, amp state 1-->0')
            elif bl.bytes_received == 5 and bl.buffer[3] == 49:  # '1', amp appears on
                amp_state = 3  # amp is powered on.
                kpa500.update_kpa500_data(4, '1')
                kpa500.update_kpa500_data(6, 'AMP ON')
                kpa500.enqueue_command(kpa500.initial_queries)
                if verbosity > 3:
                    print(f'amp state 1-->3')
            elif bl.bytes_received == 4 and bl.buffer[3] == 59:  # ';', amp connected but off.
                amp_state = 2
                kpa500.update_kpa500_data(4, '0')
                kpa500.update_kpa500_data(6, 'AMP OFF')
                if verbosity > 3:
                    print('amp state 1-->2')
            else:
                if verbosity > 1:
                    print(f'1: unexpected data {bl.buffer[:bl.bytes_received]}')
        elif amp_state == 2:  # connected, power off.
            query = kpa500.dequeue_command()
            # throw away any queries except the ON command.
            if query is not None and query == b'^ON1;':  # turn on amplifier
                await kpa500_send_receive(amp_serial_port, b'P', bl)
                kpa500.update_kpa500_data(6, 'Powering On')
                await asyncio.sleep(1.50)
                amp_state = 0  # test state again.
                if verbosity > 3:
                    print('amp state 2-->0')
            else:
                await kpa500_send_receive(amp_serial_port, b'^ON;', bl, timeout=1.5)  # hi there.
                # is b'^ON1;' when amp is on.
                # is b'^ON;' when amp is off
                # is b'' when amp is not found.
                if bl.bytes_received == 0:
                    amp_state = 1
                    kpa500.update_kpa500_data(4, '0')  # not powered
                    kpa500.update_kpa500_data(6, 'NO AMP')
                    if verbosity > 3:
                        print('no data, amp state 2-->1')
                elif bl.bytes_received == 5 and bl.buffer[3] == 49:  # '1', amp appears on
                    amp_state = 3  # amp is powered on.
                    kpa500.update_kpa500_data(4, '1')
                    kpa500.update_kpa500_data(6, 'AMP ON')
                    kpa500.enqueue_command(kpa500.initial_queries)
                    if verbosity > 3:
                        print(f'amp state 2-->3')
                elif bl.bytes_received == 4 and bl.buffer[3] == 59:  # ';', amp connected but off.
                    pass  # this is the expected result when amp is off
                else:
                    if verbosity > 3:
                        print(f'2: unexpected data {bl.buffer[:bl.bytes_received]}')
        elif amp_state == 3:  # connected, power on.
            query = kpa500.dequeue_command()
            if query is None:
                query = kpa500.normal_queries[next_command]
                if next_command == len(kpa500.normal_queries) - 1:  # this is the last one
                    next_command = 0
                else:
                    next_command += 1
            await kpa500_send_receive(amp_serial_port, query, bl)
            if query == b'^ON0;':
                amp_state = 1
                if verbosity > 3:
                    print('power off command, amp state 3-->1')
                kpa500.update_kpa500_data(6, 'PWR OFF')
                kpa500.set_amp_off_data()
                await asyncio.sleep(1.50)
            else:
                if bl.bytes_received > 0:
                    kpa500.process_kpa500_message(bl.data().decode())
                else:
                    amp_state = 0
                    kpa500.update_kpa500_data(6, 'NO AMP')
                    kpa500.set_amp_off_data()
                    if verbosity > 3:
                        print('no response, amp state 3-->0')
        else:
            print(f'invalid amp state: {amp_state}, bye bye.')
            run_loop = False

        await asyncio.sleep(0.025)  # 40/sec


async def main():
    global port, restart, username, password
    config = read_config()
    username = config.get('username')
    password = config.get('password')

    tcp_port = safe_int(config.get('tcp_port') or DEFAULT_TCP_PORT, DEFAULT_TCP_PORT)
    if tcp_port < 0 or tcp_port > 65535:
        tcp_port = DEFAULT_TCP_PORT
    web_port = safe_int(config.get('web_port') or DEFAULT_WEB_PORT, DEFAULT_WEB_PORT)
    if web_port < 0 or web_port > 65535:
        web_port = DEFAULT_WEB_PORT

    ap_mode = config.get('ap_mode', False)

    connected = True
    if upython:
        try:
            ip_address = connect_to_network(config)
            connected = ip_address is not None
        except Exception as ex:
            connected = False
            print(type(ex), ex)

    if upython:
        asyncio.create_task(morse_sender())

    port = SerialPort(baudrate=38400, timeout=0)  # timeout is zero because we do not want to block

    if connected:
        ntp_time = ntp.get_ntp_time()
        if ntp_time is None:
            print('ntp time query failed.  clock may be inaccurate.')
        else:
            print('Got time from NTP: {}'.format(get_timestamp()))

        print('Starting web service on port {}'.format(web_port))
        asyncio.create_task(asyncio.start_server(serve_http_client, '0.0.0.0', web_port))
        print('Starting tcp service on port {}'.format(tcp_port))
        asyncio.create_task(asyncio.start_server(serve_network_client, '0.0.0.0', tcp_port))
    else:
        print('no network connection')

    asyncio.create_task(kpa500_server(port, 3))

    if upython:
        last_pressed = button.value() == 0
    else:
        last_pressed = False

    while True:
        if upython:
            await asyncio.sleep(0.25)
            pressed = button.value() == 0
            if not last_pressed and pressed:  # look for activating edge
                ap_mode = not ap_mode
                config['ap_mode'] = ap_mode
                save_config(config)
                restart = True
            last_pressed = pressed

            if restart:
                machine.soft_reset()
        else:
            await asyncio.sleep(10.0)


if __name__ == '__main__':
    print('starting')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('bye')
    finally:
        asyncio.new_event_loop()  # why? to drain?
    print('done')
