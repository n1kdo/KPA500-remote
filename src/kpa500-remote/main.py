#
# main.py -- this is the web server for the Raspberry Pi Pico W Web IOT thing.
#
__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2022, J. B. Otterson N1KDO.'

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

import gc
import json
import os
import re
import sys
import time

from http_server import HttpServer
from kpa500 import ClientData, KPA500
from morse_code import MorseCode

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

        @staticmethod
        def reset():
            print('Machine.reset()')

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

onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
onboard.on()
morse_led = machine.Pin(2, machine.Pin.OUT, value=0)  # status LED
reset_button = machine.Pin(3, machine.Pin.IN, machine.Pin.PULL_UP)


BUFFER_SIZE = 4096
CONFIG_FILE = 'data/config.json'
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

# globals...
restart = False
username = ''
password = ''
http_server = HttpServer(content_dir='content/')
kpa500 = KPA500()
morse_code_sender = MorseCode(morse_led)


def get_timestamp(tt=None):
    if tt is None:
        tt = time.gmtime()
    return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}Z'.format(tt[0], tt[1], tt[2], tt[3], tt[4], tt[5])


def read_config():
    try:
        with open(CONFIG_FILE, 'r') as config_file:
            return json.load(config_file)
    except Exception as ex:
        print('failed to load configuration!', type(ex), ex)
        raise ex


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
    if http_server.FILE_EXTENSION_TO_CONTENT_TYPE_MAP.get(extension) is None:
        return False
    return True


def connect_to_network(config):
    network.country('US')
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
            network.hostname(hostname)

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
            network.hostname(hostname)

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
            morse_code_sender.set_message('ERR')
            # return None
            raise RuntimeError('Network connection failed')

    status = wlan.ifconfig()
    ip_address = status[0]
    message = 'AP {}  '.format(ip_address) if access_point_mode else '{} '.format(ip_address)
    message = message.replace('.', ' ')
    morse_code_sender.set_message(message)
    print(message)
    return ip_address


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


async def serve_network_client(reader, writer):
    """
    this provides KPA500-Remote compatible control.
    """
    verbosity = 3  # 3 is info, 4 is debug, 5 is trace, or something like that.
    t0 = milliseconds()
    extra = writer.get_extra_info('peername')
    client_name = f'{extra[0]}:{extra[1]}'
    client_data = ClientData(client_name)
    client_data.update_list.extend((7, 16, 6, 0, 1, 2, 3, 4, 8, 5, 9, 10, 11, 12, 13, 14, 15, 17, 18))  # items to send.
    kpa500.network_clients.append(client_data)
    if verbosity > 2:
        print(f'client {client_name} connected')

    try:
        while client_data.connected:
            try:
                message = await asyncio.wait_for(read_network_client(reader), 0.05)
                timed_out = False
            except TimeoutError:
                message = None
                timed_out = True
            if message is not None and not timed_out:
                client_data.last_activity = milliseconds()
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
                    client_data.last_activity = milliseconds()
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
                    if verbosity > 2:
                        print(f'client {client_data} response was None, setting connected=false')
                    client_data.connected = False

            # send any outstanding data back...
            if len(client_data.update_list) > 0:
                index = client_data.update_list.pop(0)
                writer.write(kpa500.key_names[index])
                payload = f'::{kpa500.kpa500_data[index]}\n'.encode()
                writer.write(payload)
                await writer.drain()
                client_data.last_activity = milliseconds()
                if verbosity > 3:
                    print(f'sent "{kpa500.key_names[index].decode()}{payload.decode().strip()}"')

            since_last_activity = milliseconds() - client_data.last_activity
            if since_last_activity > 15000:
                writer.write(b'\n')
                await writer.drain()
                client_data.last_activity = milliseconds()
                if verbosity > 3:
                    print(f'{get_timestamp()}: SENT keepalive TO client {client_name}')

            gc.collect()

        # connection closing
        print(f'client {client_name} connection closing...')
        writer.close()
        await writer.wait_closed()
    except Exception as ex:
        print(f'client {client_name} exception in serve_network_client:', type(ex), ex)
        raise ex
    finally:
        print(f'client {client_name} disconnected')
        found_network_client = None
        for network_client in kpa500.network_clients:
            if network_client.client_name == client_data.client_name:
                found_network_client = network_client
                break
        if found_network_client is not None:
            kpa500.network_clients.remove(found_network_client)
            print(f'client {client_name} removed from network_clients list.')
    tc = milliseconds()
    print(f'client {client_name} disconnected, elapsed time {((tc - t0) / 1000.0):6.3f} seconds')


# noinspection PyUnusedLocal
async def slash_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/'
    http_status = 301
    bytes_sent = http.send_simple_response(writer, http_status, None, None, ['Location: /kpa500.html'])
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_config_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/api/config'
    if verb == 'GET':
        payload = read_config()
        # payload.pop('secret')  # do not return the secret
        response = json.dumps(payload).encode('utf-8')
        http_status = 200
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
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
        remote_username = args.get('username')
        if remote_username is not None:
            if 1 <= len(remote_username) <= 16:
                config['username'] = remote_username
                dirty = True
            else:
                errors = True
        remote_password = args.get('password')
        if remote_password is not None:
            if 1 <= len(remote_password) <= 16:
                config['password'] = remote_password
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
            bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
        else:
            response = b'parameter out of range\r\n'
            http_status = 400
            bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        response = b'GET or PUT only.'
        http_status = 400
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_get_files_callback(http, verb, args, reader, writer, request_headers=None):
    if verb == 'GET':
        payload = os.listdir(http.content_dir)
        response = json.dumps(payload).encode('utf-8')
        http_status = 200
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    else:
        http_status = 400
        response = b'only GET permitted'
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_upload_file_callback(http, verb, args, reader, writer, request_headers=None):
    if verb == 'POST':
        boundary = None
        request_content_type = request_headers.get('content-type') or ''
        if ';' in request_content_type:
            pieces = request_content_type.split(';')
            request_content_type = pieces[0]
            boundary = pieces[1].strip()
            if boundary.startswith('boundary='):
                boundary = boundary[9:]
        if request_content_type != http.CT_MULTIPART_FORM or boundary is None:
            response = b'multipart boundary or content type error'
            http_status = 400
        else:
            response = b'unhandled problem'
            http_status = 500
            request_content_length = int(request_headers.get('content-length') or '0')
            remaining_content_length = request_content_length
            start_boundary = http.HYPHENS + boundary
            end_boundary = start_boundary + http.HYPHENS
            state = http.MP_START_BOUND
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
                    if state == http.MP_DATA:
                        if not output_file:
                            output_file = open(http.content_dir + 'uploaded_' + filename, 'wb')
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
                            state = http.MP_END_BOUND
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
                        if state == http.MP_START_BOUND:
                            if line == start_boundary:
                                state = http.MP_HEADERS
                            else:
                                print('expecting start boundary, got ' + line)
                        elif state == http.MP_HEADERS:
                            if len(line) == 0:
                                state = http.MP_DATA
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
                        elif state == http.MP_END_BOUND:
                            if line == end_boundary:
                                state = http.MP_START_BOUND
                            else:
                                print('expecting end boundary, got ' + line)
                        else:
                            http_status = 500
                            response = 'unmanaged state {}'.format(state).encode('utf-8')
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        response = b'PUT only.'
        http_status = 400
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_rename_file_callback(http, verb, args, reader, writer, request_headers=None):
    filename = args.get('filename')
    newname = args.get('newname')
    if valid_filename(filename) and valid_filename(newname):
        filename = http.content_dir + filename
        newname = http.content_dir + newname
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
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_restart_callback(http, verb, args, reader, writer, request_headers=None):
    global restart
    if upython:
        restart = True
        response = b'ok\r\n'
        http_status = 200
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        http_status = 400
        response = b'not permitted except on PICO-W'
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


# KPA500 specific APIs
# noinspection PyUnusedLocal
async def api_clear_fault_callback(http, verb, args, reader, writer, request_headers=None):
    kpa500.enqueue_command(b'^FLC;')
    response = b'ok\r\n'
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_set_band_callback(http, verb, args, reader, writer, request_headers=None):
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
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_set_fan_speed_callback(http, verb, args, reader, writer, request_headers=None):
    speed = safe_int(args.get('speed', -1))
    if 0 <= speed <= 6:
        command = f'^FC{speed};^FC;'.encode()
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad fan speed parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_set_operate_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state == '0' or state == '1':
        command = f'^OS{state};^OS;'.encode()
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_set_power_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state == '0' or state == '1':
        command = f'^ON{state};'.encode()
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_set_speaker_alarm_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state == '0' or state == '1':
        command = f'^SP{state};^SP;'.encode()
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_status_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/api/status'
    payload = {'kpa500_data': kpa500.kpa500_data}
    response = json.dumps(payload).encode('utf-8')
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


async def main():
    global restart, username, password
    config = read_config()
    username = config.get('username')
    password = config.get('password')

    http_server.add_uri_callback('/', slash_callback)
    http_server.add_uri_callback('/api/config', api_config_callback)
    http_server.add_uri_callback('/api/get_files', api_get_files_callback)
    http_server.add_uri_callback('/api/upload_file', api_upload_file_callback)
    http_server.add_uri_callback('/api/rename_file', api_rename_file_callback)
    http_server.add_uri_callback('/api/restart', api_restart_callback)

    # now KPA500 specific
    http_server.add_uri_callback('/api/clear_fault', api_clear_fault_callback)
    http_server.add_uri_callback('/api/set_band', api_set_band_callback)
    http_server.add_uri_callback('/api/set_fan_speed', api_set_fan_speed_callback)
    http_server.add_uri_callback('/api/set_operate', api_set_operate_callback)
    http_server.add_uri_callback('/api/set_power', api_set_power_callback)
    http_server.add_uri_callback('/api/set_speaker_alarm', api_set_speaker_alarm_callback)
    http_server.add_uri_callback('/api/status', api_status_callback)

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
            print(type(ex), ex)
            raise ex

    if upython:
        asyncio.create_task(morse_code_sender.morse_sender())
    if connected:
        print('Starting web service on port {}'.format(web_port))
        asyncio.create_task(asyncio.start_server(http_server.serve_http_client, '0.0.0.0', web_port))
        print('Starting tcp service on port {}'.format(tcp_port))
        asyncio.create_task(asyncio.start_server(serve_network_client, '0.0.0.0', tcp_port))
    else:
        print('no network connection')

    asyncio.create_task(kpa500.kpa500_server(3))

    reset_button_pressed_count = 0

    while True:
        if upython:
            await asyncio.sleep(0.25)
            pressed = reset_button.value() == 0
            if pressed:
                reset_button_pressed_count += 1
                if reset_button_pressed_count > 7:
                    ap_mode = not ap_mode
                    config['ap_mode'] = ap_mode
                    save_config(config)
                    restart = True
            else:
                reset_button_pressed_count = 0

            if restart:
                machine.reset()
        else:
            await asyncio.sleep(10.0)


if __name__ == '__main__':
    print('starting')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('bye')
    finally:
        asyncio.new_event_loop()
    print('done')
