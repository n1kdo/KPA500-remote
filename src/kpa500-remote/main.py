#
# main.py -- this is the Raspberry Pi Pico W KAT500 & KPA500 Network Server.
#
__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2023, 2024 J. B. Otterson N1KDO.'
__version__ = '0.9.2'

#
# Copyright 2023, 2024 J. B. Otterson N1KDO.
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

import json

from http_server import (HttpServer,
                         api_rename_file_callback,
                         api_remove_file_callback,
                         api_upload_file_callback,
                         api_get_files_callback)
from kpa500 import KPA500
from kat500 import KAT500
from morse_code import MorseCode
from utils import upython, safe_int
from picow_network import PicowNetwork


if upython:
    import machine
    import micro_logging as logging
    import uasyncio as asyncio
else:
    import asyncio
    import logging


    class Machine:
        """
        fake micropython stuff
        """

        @staticmethod
        def soft_reset():
            logging.debug('Machine.soft_reset()', 'main:Machine.soft_reset()')

        @staticmethod
        def reset():
            logging.debug('Machine.reset()', 'main:Machine.reset()')

        class Pin:
            OUT = 1
            IN = 0
            PULL_UP = 0

            def __init__(self, name, options=0, value=0):
                self.name = name
                self.options = options
                self.state = value

            def on(self):
                self.state = 1

            def off(self):
                self.state = 0

            def value(self):
                return self.state


    machine = Machine()

onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
morse_led = machine.Pin(2, machine.Pin.OUT, value=0)  # status LED
reset_button = machine.Pin(3, machine.Pin.IN, machine.Pin.PULL_UP)

BUFFER_SIZE = 4096
CONFIG_FILE = 'data/config.json'
DANGER_ZONE_FILE_NAMES = (
    'config.html',
    'files.html',
    'kat500.html',
    'kpa500.html',
)
# noinspection SpellCheckingInspection
DEFAULT_SECRET = 'elecraft'
DEFAULT_SSID = 'kpa500'
DEFAULT_KPA500_TCP_PORT = 4626
DEFAULT_KAT500_TCP_PORT = 4627
DEFAULT_WEB_PORT = 80

# globals...
keep_running = True
kpa500 = None
kat500 = None


def read_config():
    try:
        with open(CONFIG_FILE, 'r') as config_file:
            config = json.load(config_file)
    except Exception as ex:
        logging.error(f'failed to load configuration! {type(ex)} {ex}', 'main:read_config')
        config = {
            'SSID': DEFAULT_SSID,
            'secret': DEFAULT_SSID,
            'username': 'admin',
            'password': 'admin',
            'dhcp': True,
            'hostname': 'kpa500',
            'ip_address': '192.168.1.73',
            'netmask': '255.255.255.0',
            'gateway': '192.168.1.1',
            'dns_server': '8.8.8.8',
            'kpa_tcp_port': str(DEFAULT_KPA500_TCP_PORT),
            'kat_tcp_port': str(DEFAULT_KAT500_TCP_PORT),
            'web_port': str(DEFAULT_WEB_PORT),
        }
    return config


def save_config(config):
    with open(CONFIG_FILE, 'w') as config_file:
        json.dump(config, config_file)


# noinspection PyUnusedLocal
async def slash_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/'
    http_status = 301
    bytes_sent = http.send_simple_response(writer, http_status, None, None, ['Location: /kpa500.html'])
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_config_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/api/config'
    if verb == 'GET':
        payload = read_config()
        payload.pop('secret')  # do not return the secret
        response = json.dumps(payload).encode('utf-8')
        http_status = 200
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    elif verb == 'POST':
        config = read_config()
        dirty = False
        errors = []
        kat_tcp_port = args.get('kat_tcp_port')
        if kat_tcp_port is not None:
            kat_tcp_port_int = safe_int(kat_tcp_port, -2)
            if 0 <= kat_tcp_port_int <= 65535:
                config['kat_tcp_port'] = kat_tcp_port_int
                dirty = True
            else:
                errors.append('kat_tcp_port')
        kpa_tcp_port = args.get('kpa_tcp_port')
        if kpa_tcp_port is not None:
            kpa_tcp_port_int = safe_int(kpa_tcp_port, -2)
            if 0 <= kpa_tcp_port_int <= 65535:
                config['kpa_tcp_port'] = kpa_tcp_port_int
                dirty = True
            else:
                errors.append('kpa_tcp_port')
        web_port = args.get('web_port')
        if web_port is not None:
            web_port_int = safe_int(web_port, -2)
            if 0 <= web_port_int <= 65535:
                config['web_port'] = web_port
                dirty = True
            else:
                errors.append('web_port')
        ssid = args.get('SSID')
        if ssid is not None:
            if 0 < len(ssid) < 64:
                config['SSID'] = ssid
                dirty = True
            else:
                errors.append('SSID')
        secret = args.get('secret')
        if secret is not None and len(secret):
            if 8 <= len(secret) < 32:
                config['secret'] = secret
                dirty = True
            else:
                errors.append('secret')
        remote_username = args.get('username')
        if remote_username is not None:
            if 1 <= len(remote_username) <= 16:
                config['username'] = remote_username
                dirty = True
            else:
                errors.append('username')
        remote_password = args.get('password')
        if remote_password is not None:
            if 1 <= len(remote_password) <= 16:
                config['password'] = remote_password
                dirty = True
            else:
                errors.append('password')
        ap_mode_arg = args.get('ap_mode')
        if ap_mode_arg is not None:
            ap_mode = ap_mode_arg == '1'
            config['ap_mode'] = ap_mode
            dirty = True
        dhcp_arg = args.get('dhcp')
        if dhcp_arg is not None:
            dhcp = dhcp_arg == 1
            config['dhcp'] = dhcp
            dirty = True
        hostname = args.get('hostname')
        if hostname is not None:
            if 1 <= len(hostname) <= 16:
                config['hostname'] = hostname
                dirty = True
            else:
                errors.append('hostname')
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
            response = f'parameter(s) out of range\r\n {", ".join(errors)}'.encode('utf-8')
            http_status = 400
            bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        response = b'GET or PUT only.'
        http_status = 400
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_restart_callback(http, verb, args, reader, writer, request_headers=None):
    global keep_running
    if upython:
        keep_running = False
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
async def api_kpa_clear_fault_callback(http, verb, args, reader, writer, request_headers=None):
    kpa500.enqueue_command(b'^FLC;')
    response = b'ok\r\n'
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_kpa_set_band_callback(http, verb, args, reader, writer, request_headers=None):
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
async def api_kpa_set_fan_speed_callback(http, verb, args, reader, writer, request_headers=None):
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
async def api_kpa_set_operate_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
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
async def api_kpa_set_power_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
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
async def api_kpa_set_speaker_alarm_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
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
async def api_kpa_status_callback(http, verb, args, reader, writer, request_headers=None):  # '/api/kpa_status'
    payload = {'kpa500_data': kpa500.device_data}
    response = json.dumps(payload).encode('utf-8')
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


# KAT500 specific APIs
# noinspection PyUnusedLocal
async def api_kat_status_callback(http, verb, args, reader, writer, request_headers=None):  # '/api/kpa_status'
    payload = {'kat500_data': kat500.device_data}
    response = json.dumps(payload).encode('utf-8')
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


async def api_kat_set_power_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = f'PS{state};PS;'.encode()
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_kat_set_antenna_callback(http, verb, args, reader, writer, request_headers=None):
    antenna = args.get('antenna')
    if antenna in ('0', '1', '2', '3'):
        command = f'AN{antenna};AN;'.encode()
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad antenna parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_kat_set_mode_callback(http, verb, args, reader, writer, request_headers=None):
    mode = args.get('mode')
    if mode in ('A', 'M', 'B'):
        command = f'MD{mode};MD;'.encode()
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad mode parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_kat_set_tune_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        if state == '1':
            command = f'FT;TP;'.encode()
        else:
            command = f'CT;TP;'.encode()
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_kat_clear_fault_callback(http, verb, args, reader, writer, request_headers=None):
    kat500.enqueue_command(b'FLTC;FLT;')
    response = b'ok\r\n'
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_kat_set_ampi_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = f'AMPI{state};AMPI;'.encode()
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_kat_set_attn_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = f'ATTN{state};ATTN;'.encode()
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_kat_set_bypass_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        if state == '1':
            command = b'BYPB;BYP;'
        else:
            command = b'BYPN;BYP;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = 200
    else:
        response = b'bad state parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def main():
    global keep_running, kpa500, kat500

    logging.info('Starting...', 'main:main')

    config = read_config()
    username = config.get('username')
    password = config.get('password')

    kpa500_tcp_port_s = config.get('kpa_tcp_port')
    if kpa500_tcp_port_s is None:
        kpa500_tcp_port_s = str(DEFAULT_KPA500_TCP_PORT)
        config['kpa_tcp_port'] = kpa500_tcp_port_s
    kat500_tcp_port_s = config.get('kat_tcp_port')
    if kat500_tcp_port_s is None:
        kat500_tcp_port_s = str(DEFAULT_KAT500_TCP_PORT)
        config['kpa_kat_port'] = kat500_tcp_port_s

    kpa500_tcp_port = safe_int(kpa500_tcp_port_s)
    if kpa500_tcp_port < 0 or kpa500_tcp_port > 65535:
        kpa500_tcp_port = DEFAULT_KPA500_TCP_PORT
    kat500_tcp_port = safe_int(kat500_tcp_port_s)
    if kat500_tcp_port < 0 or kat500_tcp_port > 65535:
        kat500_tcp_port = DEFAULT_KAT500_TCP_PORT

    if upython:
        kat500_port = '1'
        kpa500_port = '0'
    else:
        kat500_port = 'com1'
        kpa500_port = 'com2'

    web_port = safe_int(config.get('web_port') or DEFAULT_WEB_PORT, DEFAULT_WEB_PORT)
    if web_port < 0 or web_port > 65535:
        web_port = DEFAULT_WEB_PORT
        config['web_port'] = str(web_port)

    ap_mode = config.get('ap_mode', False)

    if upython:
        picow_network = PicowNetwork(config, DEFAULT_SSID, DEFAULT_SECRET)
        network_keepalive_task = asyncio.create_task(picow_network.keep_alive())
        morse_code_sender = MorseCode(morse_led)
        morse_sender_task = asyncio.create_task(morse_code_sender.morse_sender())

    http_server = HttpServer(content_dir='content/')
    http_server.add_uri_callback('/', slash_callback)
    http_server.add_uri_callback('/api/config', api_config_callback)
    http_server.add_uri_callback('/api/get_files', api_get_files_callback)
    http_server.add_uri_callback('/api/upload_file', api_upload_file_callback)
    http_server.add_uri_callback('/api/remove_file', api_remove_file_callback)
    http_server.add_uri_callback('/api/rename_file', api_rename_file_callback)
    http_server.add_uri_callback('/api/restart', api_restart_callback)

    # KPA500 specific
    if kpa500_tcp_port != 0:
        kpa500 = KPA500(username=username, password=password, port_name=kpa500_port)
        http_server.add_uri_callback('/api/kpa_clear_fault', api_kpa_clear_fault_callback)
        http_server.add_uri_callback('/api/kpa_set_band', api_kpa_set_band_callback)
        http_server.add_uri_callback('/api/kpa_set_fan_speed', api_kpa_set_fan_speed_callback)
        http_server.add_uri_callback('/api/kpa_set_operate', api_kpa_set_operate_callback)
        http_server.add_uri_callback('/api/kpa_set_power', api_kpa_set_power_callback)
        http_server.add_uri_callback('/api/kpa_set_speaker_alarm', api_kpa_set_speaker_alarm_callback)
        http_server.add_uri_callback('/api/kpa_status', api_kpa_status_callback)
        logging.info(f'Starting KPA500 client service on port {kpa500_tcp_port}', 'main:main')
        kpa500_client_server = asyncio.create_task(asyncio.start_server(kpa500.serve_kpa500_remote_client,
                                                                        '0.0.0.0', kpa500_tcp_port))
        # this task talks to the amplifier hardware.
        logging.info(f'Starting KPA500 amplifier service', 'main:main')
        kpa500_server = asyncio.create_task(kpa500.kpa500_server())

    # KAT500 specific
    if kat500_tcp_port != 0:
        kat500 = KAT500(username=username, password=password, port_name=kat500_port)
        http_server.add_uri_callback('/api/kat_status', api_kat_status_callback)
        http_server.add_uri_callback('/api/kat_set_power', api_kat_set_power_callback)
        http_server.add_uri_callback('/api/kat_set_tune', api_kat_set_tune_callback)
        http_server.add_uri_callback('/api/kat_set_antenna', api_kat_set_antenna_callback)
        http_server.add_uri_callback('/api/kat_set_mode', api_kat_set_mode_callback)
        http_server.add_uri_callback('/api/kat_set_ampi', api_kat_set_ampi_callback)
        http_server.add_uri_callback('/api/kat_set_attn', api_kat_set_attn_callback)
        http_server.add_uri_callback('/api/kat_set_bypass', api_kat_set_bypass_callback)
        http_server.add_uri_callback('/api/kat_clear_fault', api_kat_clear_fault_callback)
        logging.info(f'Starting KAT500 client service on port {kat500_tcp_port}', 'main:main')
        kat500_client_server = asyncio.create_task(asyncio.start_server(kat500.serve_kat500_remote_client,
                                                                        '0.0.0.0', kat500_tcp_port))
        # this task talks to the tuner hardware.
        logging.info(f'Starting KAT500 tuner service', 'main:main')
        kat500_server = asyncio.create_task(kat500.kat500_server())

    logging.info(f'Starting web service on port {web_port}', 'main:main')
    web_server = asyncio.create_task(asyncio.start_server(http_server.serve_http_client, '0.0.0.0', web_port))

    reset_button_pressed_count = 0
    four_count = 0
    last_message = ''
    while keep_running:
        if upython:
            await asyncio.sleep(0.25)
            four_count += 1
            pressed = reset_button.value() == 0
            if pressed:
                reset_button_pressed_count += 1
            else:
                if reset_button_pressed_count > 0:
                    reset_button_pressed_count -= 1
            if reset_button_pressed_count > 7:
                logging.info('reset button pressed', 'main:main')
                ap_mode = not ap_mode
                config['ap_mode'] = ap_mode
                save_config(config)
                keep_running = False
            if four_count >= 3:  # check for new message every one second
                if picow_network.get_message() != last_message:
                    last_message = picow_network.get_message()
                    morse_code_sender.set_message(last_message)
                four_count = 0
        else:
            await asyncio.sleep(10.0)
    if upython:
        machine.soft_reset()


if __name__ == '__main__':
    logging.loglevel = logging.INFO  # DEBUG
    logging.info('starting', 'main:__main__')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('bye', 'main:__main__')
    finally:
        asyncio.new_event_loop()
    logging.info('done', 'main:__main__')
