#
# main.py -- this is the Raspberry Pi Pico W KAT500 & KPA500 Network Server.
#
__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2023, 2024, 2025, 2026 J. B. Otterson N1KDO.'
__version__ = '0.10.34'  # 2026-11-01

#
# Copyright 2023, 2024, 2025, 2026 J. B. Otterson N1KDO.
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

# Import scratch blocks: as modules import, their code objects fragment the heap until
# no large contiguous block survives (measured: largest free block ~2 KB after all
# imports). Two allocations in this startup sequence need one: HttpServer's 4 KB
# response buffer and picow_network's largest code object (~2.1 KB). Pin an 8 KB
# block before any import; dropping it immediately before each of those allocations
# guarantees a contiguous block exists, so neither depends on import order or on the
# sizes of the other modules. The dropped memory simply joins the free pool.
# this is a revolting hack to work around the small heap on the Pico-W.
_import_scratch_a = bytes(8192)  # for HttpServer's response buffer
_import_scratch_b = bytes(8192)  # for picow_network's import

from utils import safe_int, upython, is_pico2, is_ipv4, is_hostname, make_ssl_server_context
import asyncio
import gc

from config_data import (ConfigData,
                         DEFAULT_SSID, DEFAULT_SECRET,
                         DEFAULT_KAT500_TCP_PORT, DEFAULT_KPA500_TCP_PORT)
from http_server import (HttpServer,
                         HTTP_STATUS_OK, HTTP_STATUS_BAD_REQUEST, HTTP_STATUS_MOVED_PERMANENTLY,
                         HTTP_VERB_GET, HTTP_VERB_POST)

CONTENT_DIR = 'content/'
_import_scratch_a = None
gc.collect()
http_server = HttpServer(content_dir=CONTENT_DIR)

if upython:
    import machine

    _import_scratch_b = None
    gc.collect()
    from picow_network import PicowNetwork

    try:
        from watchdog import Watchdog
    except ImportError:
        Watchdog = None
else:
    from not_machine import machine
    import sys

    Watchdog = None

from kpa500 import KPA500
from kat500 import KAT500
from morse_code import MorseCode

import micro_logging as logging

picow_network: PicowNetwork | None = None

onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
morse_led = machine.Pin(2, machine.Pin.OUT, value=0)  # status LED
ap_mode_button = machine.Pin(3, machine.Pin.IN, machine.Pin.PULL_UP)

# globals...
keep_running = True
kpa500: KPA500 | None = None
kat500: KAT500 | None = None

# config data
config = ConfigData()


# noinspection PyUnusedLocal
@http_server.route(b'/')
async def slash_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/'
    http_status = HTTP_STATUS_MOVED_PERMANENTLY
    bytes_sent = await http.send_simple_response(writer, http_status, None, None, [b'Location: /kpa500.html'])
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/config')
async def api_config_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/api/config'
    if verb == HTTP_VERB_GET:
        payload = config.get_data().copy()
        payload.pop('secret', None)  # do not return the secret
        http_status = HTTP_STATUS_OK
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_APP_JSON, payload)
    elif verb == HTTP_VERB_POST:
        errors = []
        kat_tcp_port = args.get('kat_tcp_port')
        kat_tcp_port_int = None
        if kat_tcp_port is not None:
            kat_tcp_port_int = safe_int(kat_tcp_port, -2)
            if not 0 <= kat_tcp_port_int <= 65535:
                errors.append('kat_tcp_port')
        kpa_tcp_port = args.get('kpa_tcp_port')
        kpa_tcp_port_int = None
        if kpa_tcp_port is not None:
            kpa_tcp_port_int = safe_int(kpa_tcp_port, -2)
            if not 0 <= kpa_tcp_port_int <= 65535:
                errors.append('kpa_tcp_port')
        # the KPA500 and KAT500 client servers must bind different ports.
        if ((kat_tcp_port is not None or kpa_tcp_port is not None)
                and 'kat_tcp_port' not in errors and 'kpa_tcp_port' not in errors):
            eff_kat = kat_tcp_port_int if kat_tcp_port_int is not None else safe_int(
                config.get('kat_tcp_port'), DEFAULT_KAT500_TCP_PORT)
            eff_kpa = kpa_tcp_port_int if kpa_tcp_port_int is not None else safe_int(
                config.get('kpa_tcp_port'), DEFAULT_KPA500_TCP_PORT)
            if eff_kat == eff_kpa:
                errors.append('kat_tcp_port==kpa_tcp_port')
        if kat_tcp_port_int is not None and 'kat_tcp_port' not in errors:
            config['kat_tcp_port'] = kat_tcp_port_int
        if kpa_tcp_port_int is not None and 'kpa_tcp_port' not in errors:
            config['kpa_tcp_port'] = kpa_tcp_port_int
        ssid = args.get('SSID')
        if ssid is not None:
            # PicowNetwork only accepts SSIDs of 32 chars or fewer.
            if 0 < len(ssid) <= 32:
                config['SSID'] = ssid
            else:
                errors.append('SSID')
        secret = args.get('secret')
        if secret is not None and len(secret):
            if 8 <= len(secret) <= 32:
                config['secret'] = secret
            else:
                errors.append('secret')
        remote_username = args.get('username')
        if remote_username is not None:
            if 1 <= len(remote_username) <= 16:
                config['username'] = remote_username
            else:
                errors.append('username')
        remote_password = args.get('password')
        if remote_password is not None:
            if 1 <= len(remote_password) <= 16:
                config['password'] = remote_password
            else:
                errors.append('password')
        dhcp_arg = args.get('dhcp')
        if dhcp_arg is not None:
            dhcp = dhcp_arg == '1'
            config['dhcp'] = dhcp
        hostname = args.get('hostname')
        if hostname is not None:
            if 1 <= len(hostname) <= 32 and is_hostname(hostname):  # 32 = network.hostname() limit
                config['hostname'] = hostname
            else:
                errors.append('hostname')
        ip_address = args.get('ip_address')
        if ip_address is not None:
            if is_ipv4(ip_address):
                config['ip_address'] = ip_address
            else:
                errors.append('ip_address')
        netmask = args.get('netmask')
        if netmask is not None:
            if is_ipv4(netmask):
                config['netmask'] = netmask
            else:
                errors.append('netmask')
        gateway = args.get('gateway')
        if gateway is not None:
            if is_ipv4(gateway):
                config['gateway'] = gateway
            else:
                errors.append('gateway')
        dns_server = args.get('dns_server')
        if dns_server is not None:
            if is_ipv4(dns_server):
                config['dns_server'] = dns_server
            else:
                errors.append('dns_server')
        if not errors:
            response = b'ok\r\n'
            http_status = HTTP_STATUS_OK
            bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
        else:
            response = f'error(s): {", ".join(errors)}\r\n'.encode('utf-8')
            http_status = HTTP_STATUS_BAD_REQUEST
            bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        response = b'GET or POST only.'
        http_status = HTTP_STATUS_BAD_REQUEST
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/restart')
async def api_restart_callback(http, verb, args, reader, writer, request_headers=None):
    global keep_running
    if upython:
        keep_running = False
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        http_status = HTTP_STATUS_BAD_REQUEST
        response = b'not permitted except on PICO-W'
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# KPA500 specific APIs
# noinspection PyUnusedLocal
@http_server.route(b'/api/kpa_clear_fault')
async def api_kpa_clear_fault_callback(http, verb, args, reader, writer, request_headers=None):
    kpa500.enqueue_command(b'^FLC;FL;')
    response = b'ok\r\n'
    http_status = HTTP_STATUS_OK
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/kpa_set_band')
async def api_kpa_set_band_callback(http, verb, args, reader, writer, request_headers=None):
    band_name = args.get('band')
    # encode at the HTTP boundary so band_label_to_number() stays bytes-only
    band_number = kpa500.band_label_to_number(band_name.encode()) if band_name is not None else None
    if band_number is not None:
        command = b'^BN%02d;' % band_number
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad band name parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/kpa_set_fan_speed')
async def api_kpa_set_fan_speed_callback(http, verb, args, reader, writer, request_headers=None):
    speed = safe_int(args.get('speed'), -1)
    if 0 <= speed <= 6:
        command = b'^FC%d;^FC;' % speed
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad fan speed parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/kpa_set_operate')
async def api_kpa_set_operate_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = b'^OS1;^OS;' if state == '1' else b'^OS0;^OS;'
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/kpa_set_power')
async def api_kpa_set_power_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = b'^ON1;' if state == '1' else b'^ON0;'
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/kpa_set_speaker_alarm')
async def api_kpa_set_speaker_alarm_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = b'^SP1;^SP;' if state == '1' else b'^SP0;^SP;'
        kpa500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
@http_server.route(b'/api/kpa_status')
async def api_kpa_status_callback(http, verb, args, reader, writer, request_headers=None):  # '/api/kpa_status'
    payload = {'kpa500_data': kpa500.device_data}
    http_status = HTTP_STATUS_OK
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_APP_JSON, payload)
    return bytes_sent, http_status


# KAT500 specific APIs
# noinspection PyUnusedLocal
@http_server.route(b'/api/kat_status')
async def api_kat_status_callback(http, verb, args, reader, writer, request_headers=None):  # '/api/kat_status'
    payload = {'kat500_data': kat500.device_data}
    http_status = HTTP_STATUS_OK
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_APP_JSON, payload)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_set_power')
async def api_kat_set_power_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = b'PS1;PS;' if state == '1' else b'PS0;PS;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_set_antenna')
async def api_kat_set_antenna_callback(http, verb, args, reader, writer, request_headers=None):
    antenna = args.get('antenna')
    if antenna in ('0', '1', '2', '3'):
        command = b'AN0;AN;' if antenna == '0' else b'AN1;AN;' if antenna == '1' else b'AN2;AN;' if antenna == '2' else b'AN3;AN;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad antenna parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_set_mode')
async def api_kat_set_mode_callback(http, verb, args, reader, writer, request_headers=None):
    mode = args.get('mode')
    if mode in ('A', 'M', 'B'):
        command = b'MDA;MD;' if mode == 'A' else b'MDM;MD;' if mode == 'M' else b'MDB;MD;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad mode parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_set_tune')
async def api_kat_set_tune_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        if state == '1':
            command = b'FT;TP;'
        else:
            command = b'CT;TP;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_clear_fault')
async def api_kat_clear_fault_callback(http, verb, args, reader, writer, request_headers=None):
    kat500.enqueue_command(b'FLTC;FLT;')
    response = b'ok\r\n'
    http_status = HTTP_STATUS_OK
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_set_ampi')
async def api_kat_set_ampi_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = b'AMPI1;AMPI;' if state == '1' else b'AMPI0;AMPI;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_set_attn')
async def api_kat_set_attn_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        command = b'ATTN1;ATTN;' if state == '1' else b'ATTN0;ATTN;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


@http_server.route(b'/api/kat_set_bypass')
async def api_kat_set_bypass_callback(http, verb, args, reader, writer, request_headers=None):
    state = args.get('state')
    if state in ('0', '1'):
        if state == '1':
            command = b'BYPB;BYP;'
        else:
            command = b'BYPN;BYP;'
        kat500.enqueue_command(command)
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
    else:
        response = b'bad state parameter\r\n'
        http_status = HTTP_STATUS_BAD_REQUEST
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def serve_https(ssl_ctx):
    # HTTPS is only enabled on a Pico 2, whose heap comfortably holds several
    # concurrent mbedTLS wrapped sockets, so the standard parallel-streams TLS
    # server suffices.
    await asyncio.start_server(http_server.serve_http_client, '0.0.0.0', 443, ssl=ssl_ctx)


async def main():
    global keep_running, kpa500, kat500, picow_network

    logging.info('Starting...', 'main:main')

    username = config.get_bytes('username')
    password = config.get_bytes('password')

    kpa500_tcp_port_s = config.get('kpa_tcp_port')
    if kpa500_tcp_port_s is None:
        kpa500_tcp_port_s = str(DEFAULT_KPA500_TCP_PORT)
        config['kpa_tcp_port'] = kpa500_tcp_port_s
    kat500_tcp_port_s = config.get('kat_tcp_port')
    if kat500_tcp_port_s is None:
        kat500_tcp_port_s = str(DEFAULT_KAT500_TCP_PORT)
        config['kat_tcp_port'] = kat500_tcp_port_s

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
        if sys.platform == 'win32':
            kat500_port = 'com1'
            kpa500_port = 'com2'
        elif sys.platform == 'linux':
            kat500_port = '/dev/ttyS4'
            kpa500_port = '/dev/ttyS5'
        else:
            kat500_port = None
            kpa500_port = None
            logging.error(f'Unsupported platform {sys.platform}')

    ap_mode = ap_mode_button.value() == 0

    if upython:
        picow_network = PicowNetwork(config, DEFAULT_SSID, DEFAULT_SECRET, access_point_mode=ap_mode)
        morse_code_sender = MorseCode(morse_led)
        if logging.loglevel != logging.DEBUG and Watchdog is not None:
            _ = Watchdog()

    else:
        picow_network = None
        morse_code_sender = None

    # KPA500 specific
    if kpa500_tcp_port != 0:
        kpa500 = KPA500(username=username, password=password, port_name=kpa500_port)
        logging.info(f'Starting KPA500 client service on port {kpa500_tcp_port}', 'main:main')
        try:
            kpa500_client_server = await asyncio.start_server(kpa500.serve_kpa500_remote_client,
                                                              '0.0.0.0', kpa500_tcp_port)
        except Exception as e:
            logging.exception(f'could not start KPA500 client service on port {kpa500_tcp_port}',
                              'main:main', e)
            kpa500_client_server = None
        # this task talks to the amplifier hardware.
        logging.info(f'Starting KPA500 amplifier service', 'main:main')
        kpa500_server = asyncio.create_task(kpa500.kpa500_server())
    else:
        kpa500 = None
        kpa500_server = None

    # KAT500 specific
    if kat500_tcp_port != 0:
        kat500 = KAT500(username=username, password=password, port_name=kat500_port)
        logging.info(f'Starting KAT500 client service on port {kat500_tcp_port}', 'main:main')
        try:
            kat500_client_server = await asyncio.start_server(kat500.serve_kat500_remote_client,
                                                              '0.0.0.0', kat500_tcp_port)
        except Exception as e:
            logging.exception(f'could not start KAT500 client service on port {kat500_tcp_port}',
                              'main:main', e)
            kat500_client_server = None
        # this task talks to the tuner hardware.
        logging.info(f'Starting KAT500 tuner service', 'main:main')
        kat500_server = asyncio.create_task(kat500.kat500_server())
    else:
        kat500 = None
        kat500_client_server = None
        kat500_server = None

    # Web service: cleartext HTTP always on port 80.  HTTPS is additionally
    # served on port 443 on a Pico 2 when the convention-named cert/key files
    # are present and valid; in AP (setup) mode the hostname is not meaningful,
    # so HTTPS is never enabled there.
    logging.info('Starting web service on port 80', 'main:main')
    try:
        web_server = await asyncio.start_server(http_server.serve_http_client, '0.0.0.0', 80)
    except Exception as e:
        logging.exception('could not start web server on port 80', 'main:main', e)
        web_server = None

    https_server = None
    if ap_mode:
        logging.info('HTTPS disabled (AP mode)', 'main:main')
    elif not is_pico2:
        logging.info('HTTPS disabled (not a Pico 2)', 'main:main')
    else:
        ssl_ctx = make_ssl_server_context(config.get('hostname'))
        if ssl_ctx is not None:
            logging.info('Starting HTTPS service on port 443', 'main:main')
            try:
                https_server = asyncio.create_task(serve_https(ssl_ctx))
            except Exception as e:
                logging.exception('could not start HTTPS server on port 443', 'main:main', e)
                https_server = None

    ten_count = 0
    last_message = b''
    while keep_running:
        if upython:
            await asyncio.sleep(0.100)
            ten_count += 1

            if ten_count >= 10:  # every one second
                gc.collect()
                if logging.should_log(logging.INFO):
                    free = gc.mem_free()
                    alloc = gc.mem_alloc()
                    logging.info(f'Memory: {alloc} allocated, {free} free ({free / (free + alloc) * 100:6.2f}% free)')
                msg = picow_network.get_message()
                if msg != last_message:
                    last_message = msg
                    morse_code_sender.set_message(last_message)
                ten_count = 0
        else:
            await asyncio.sleep(10.0)
    if upython:
        config.flush()
        machine.soft_reset()


if __name__ == '__main__':
    logging.loglevel = logging.INFO
    # logging.loglevel = logging.DEBUG
    logging.info('starting', 'main:__main__')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('bye', 'main:__main__')
    finally:
        logging.info('finally', 'main:__main__')
        # de-init the network
        if picow_network is not None:
            picow_network.deinit()
    config.flush()

    logging.info('done', 'main:__main__')
