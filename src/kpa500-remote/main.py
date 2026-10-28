#
# main.py -- this is the Raspberry Pi Pico W KAT500 & KPA500 Network Server.
#
__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2023, 2024, 2025, 2026 J. B. Otterson N1KDO.'
__version__ = '0.10.32'  # 2026-10-25

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

# mbedTLS needs one contiguous ~23 KB block per TLS connection (in/out buffers), but the
# Pico W's Python heap fragments within minutes of normal operation until no block that
# large survives, so ssl.wrap_socket() ENOMEMs. Pin one block here, before any import
# allocates code, so it sits at the bottom of the heap: while a connection is live its
# mbedTLS buffers occupy this span; when no connection is live the span is re-pinned
# (_settle_https) and handed to mbedTLS again before each wrap. See _restore_tls_reserve().
# Sized to the measured per-connection wrap cost (~22.8 KB) plus margin; every extra
# byte pinned here is a byte stolen from the heap during module imports.
_TLS_RESERVE_SIZE = 24000
_tls_reserve = None
try:
    _tls_reserve = bytes(_TLS_RESERVE_SIZE)
except MemoryError:
    _tls_reserve = None

# Import scratch blocks: as modules import, their code objects fragment the heap until
# no large contiguous block survives (measured: largest free block ~2 KB after all
# imports). Two allocations in this startup sequence need one: HttpServer's 4 KB
# response buffer and picow_network's largest code object (~2.1 KB). Pin an 8 KB
# block before any import; dropping it immediately before each of those allocations
# guarantees a contiguous block exists, so neither depends on import order or on the
# sizes of the other modules. The dropped memory simply joins the free pool.
_import_scratch_a = bytes(8192)  # for HttpServer's response buffer
_import_scratch_b = bytes(8192)  # for picow_network's import

import asyncio
import gc
import socket

try:
    from asyncio import TimeoutError
except ImportError:
    from asyncio.exceptions import TimeoutError

try:
    from asyncio.stream import Stream
except ImportError:
    # CPython host debugging: no MicroPython asyncio Stream; serve_https() falls back
    # to asyncio.start_server(ssl=).
    Stream = None

from config_data import (ConfigData,
                         DEFAULT_SSID, DEFAULT_SECRET, DEFAULT_WEB_PORT,
                         DEFAULT_KAT500_TCP_PORT, DEFAULT_KPA500_TCP_PORT)
from http_server import (HttpServer,
                         HTTP_STATUS_OK, HTTP_STATUS_BAD_REQUEST, HTTP_STATUS_MOVED_PERMANENTLY,
                         HTTP_VERB_GET, HTTP_VERB_POST)

CONTENT_DIR = 'content/'
_import_scratch_a = None
gc.collect()
http_server = HttpServer(content_dir=CONTENT_DIR)

from utils import upython
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
from utils import upython, safe_int, is_ipv4, is_hostname, make_ssl_server_context, LineReader, milliseconds
import micro_logging as logging

picow_network: PicowNetwork | None = None

onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
morse_led = machine.Pin(2, machine.Pin.OUT, value=0)  # status LED
ap_mode_button = machine.Pin(3, machine.Pin.IN, machine.Pin.PULL_UP)

# globals...
keep_running = True
kpa500 : KPA500 | None = None
kat500 : KAT500 | None = None

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
        if kat_tcp_port is not None:
            kat_tcp_port_int = safe_int(kat_tcp_port, -2)
            if 0 <= kat_tcp_port_int <= 65535:
                config['kat_tcp_port'] = kat_tcp_port_int
            else:
                errors.append('kat_tcp_port')
        kpa_tcp_port = args.get('kpa_tcp_port')
        if kpa_tcp_port is not None:
            kpa_tcp_port_int = safe_int(kpa_tcp_port, -2)
            if 0 <= kpa_tcp_port_int <= 65535:
                config['kpa_tcp_port'] = kpa_tcp_port_int
            else:
                errors.append('kpa_tcp_port')
        web_port = args.get('web_port')
        if web_port is not None:
            web_port_int = safe_int(web_port, -2)
            if 0 <= web_port_int <= 65535:
                config['web_port'] = web_port_int
            else:
                errors.append('web_port')
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
            response = f'parameter(s) out of range\r\n {", ".join(errors)}'.encode('utf-8')
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


_tls_restore_size_last = _TLS_RESERVE_SIZE


def _restore_tls_reserve():
    # Re-pin the TLS reserve after a connection closes. The freed mbedTLS blocks coalesce
    # back into the original span, so the full size normally fits again; the last known
    # good size is next (fragmentation tends to persist between connections). If neither
    # fits, find the largest fitting size by bisection: every failed bytes() probe costs
    # a full GC in the firmware (gc_alloc collects on each miss), so the old linear walk
    # took minutes and blocked the event loop (starving the watchdog); bisection is
    # <=12 probes (~0.25 s). A span below ~22.8 KB cannot hold one wrapped socket, so
    # 22800 is the floor; if even that fails the reserve is lost until restart.
    global _tls_reserve, _tls_restore_size_last
    for size in (_TLS_RESERVE_SIZE, _tls_restore_size_last):
        try:
            _tls_reserve = bytes(size)
        except MemoryError:
            pass
        else:
            break
    else:
        # Verify the floor fits before searching above it.
        try:
            _tls_reserve = bytes(22800)
        except MemoryError:
            pass
        else:
            lo, hi = 22800, _TLS_RESERVE_SIZE - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                try:
                    _tls_reserve = bytes(mid)
                except MemoryError:
                    hi = mid - 1
                else:
                    lo = mid
    if _tls_reserve is None:
        logging.warning('TLS reserve lost; HTTPS may fail until restart', 'main:_restore_tls_reserve')
        return 0
    size = len(_tls_reserve)
    if size != _tls_restore_size_last:
        _tls_restore_size_last = size
        logging.info(f'TLS reserve restored to {size} bytes', 'main:_restore_tls_reserve')
    return size


_HTTPS_IDLE_SLICE = 2             # s; idle-wait slice; bounds eviction-notice latency
_HTTPS_FIRST_REQ_TIMEOUT = 15000  # ms; a just-wrapped conn is not evictable this long


class _HttpsConn:
    """One handshaken HTTPS client connection, served by its own asyncio task.

    state is 'wait' while blocked reading the next request line and 'busy' while a
    request is being handled.  When the heap cannot hold another wrapped socket (the
    Pico W), the idle-oldest 'wait' conn is asked to yield its mbedTLS span by setting
    evict; it notices the flag within one idle slice and exits on its own, so no task
    ever closes another task's socket.  last_done drives that pick: an actively polling
    client always has a fresh last_done and is never picked over a parked connection.
    """

    def __init__(self, sock, s2s, addr):
        global _https_next_id
        self.id = _https_next_id
        _https_next_id += 1
        self.sock = sock      # wrapped TLS socket; closed in the task's finally block
        self.s2s = s2s         # Stream view of sock, used for read/write
        self.addr = addr
        self.state = 'wait'
        self.served = 0
        self.evict = False
        born = milliseconds()
        self.born = born
        self.last_done = born


_https_pending = []   # (sock, addr) accepted raw sockets awaiting their TLS wrap
_https_live = {}      # conn.id -> _HttpsConn; wrapped sockets currently being served
_https_next_id = 1
_https_ssl_ctx = None


def _fail_wrap(s2, addr, err):
    logging.debug('HTTPS handshake failed from %s: %s' % (addr, err), 'main:_attempt_wrap')
    try:
        s2.close()
    except OSError:
        pass
    del s2
    _https_pending.pop(0)


def _pick_https_evict():
    # The live conn that should yield its span: waiting for a request, not already
    # dying, and (if it has served nothing) old enough that its client had a fair
    # chance to send the first request.  Oldest last_done wins.
    best = None
    now = milliseconds()
    for conn in _https_live.values():
        if conn.state != 'wait' or conn.evict:
            continue
        if conn.served == 0 and now - conn.born < _HTTPS_FIRST_REQ_TIMEOUT:
            continue
        if best is None or conn.last_done < best.last_done:
            best = conn
    return best


async def _attempt_wrap(ssl_ctx):
    # Wrap queued raw sockets, at most one new wrap per call.  The handshake itself
    # blocks the loop ~1.3 s (mbedTLS is synchronous), so a sleep(0) yields to the
    # event loop before each attempt.
    #
    # While no conn is live the reserved span is free, so drop the pin first and
    # wrap_socket cannot ENOMEM no matter how fragmented the rest of the heap is;
    # a failed handshake pops that client (its peer will reconnect).  With a conn
    # live, the wrap either succeeds (the heap has room, e.g. Pico 2) or ENOMEMs:
    # then the queued socket stays in the queue (raw sockets are cheap; the kernel
    # buffers its data) and the idle-oldest waiter is flagged to yield its span;
    # when that task exits, _settle_https() retries this same socket.
    global _tls_reserve
    while True:
        await asyncio.sleep(0)  # let the event loop breathe between handshakes
        if not _https_pending:  # re-check: another task may have drained it at the yield
            break
        s2, addr = _https_pending[0]
        if _tls_reserve is not None:
            # No live conn: hand the reserved span to mbedTLS.  Dropping the reference
            # frees one contiguous block at least _TLS_RESERVE_SIZE big.  The handshake
            # runs inside wrap_socket (on a blocking socket), so a connection that
            # never sends a ClientHello times out instead of hanging here.
            _tls_reserve = None
            gc.collect()
        try:
            s2.settimeout(60)
            s2w = ssl_ctx.wrap_socket(s2, server_side=True)
        except MemoryError:
            # No room: a live conn still holds the span (or the reserve was lost to
            # fragmentation).  Leave s2 queued and flag a victim, if any is eligible;
            # its task exits on its own and _settle_https() drives the retry.
            logging.debug('HTTPS wrap deferred: no memory', 'main:_attempt_wrap')
            victim = _pick_https_evict()
            if victim is not None:
                victim.evict = True
            return
        except OSError as e:
            # A browser that aborts a request (tab closed, page navigation, Chrome's
            # own connection cleanup) leaves a fatal alert or an EOF in the backlog;
            # the handshake reads it and fails.  Normal web traffic: drop quietly and
            # try the next queued client.
            _fail_wrap(s2, addr, e)
            continue
        _https_pending.pop(0)
        s2w.setblocking(False)
        conn = _HttpsConn(s2w, Stream(s2w, {"peername": addr}), addr)
        _https_live[conn.id] = conn
        conn.task = asyncio.create_task(_serve_https_conn(conn))
        return  # one new wrap per call; later events wrap the rest
    if not _https_live and _tls_reserve is None:
        _restore_tls_reserve()


async def _settle_https():
    # Drive the queue after an event (accept, request done, idle slice, conn close):
    # wrap the next queued client if any, else re-pin the reserved span.
    if _https_pending:
        await _attempt_wrap(_https_ssl_ctx)
    elif not _https_live and _tls_reserve is None:
        _restore_tls_reserve()


async def _serve_https_conn(conn):
    # Serve one handshaken connection for as long as it lives (keep-alive): a
    # handshake costs ~1.3 s of crypto, so the connection is only closed when the
    # peer goes away or when its mbedTLS span is needed by a queued client.  The
    # idle wait runs in slices so an eviction flag (or a queued client) is noticed
    # within one slice.
    lines = LineReader(conn.s2s, max_line_length=4096)  # must match _BUFFER_SIZE (const() names are not importable across modules)
    try:
        while True:
            if conn.evict:
                break
            conn.state = 'wait'
            try:
                request_line = await asyncio.wait_for(lines.readline(), _HTTPS_IDLE_SLICE)
            except TimeoutError:
                await _settle_https()
                if conn.evict:
                    break
                continue
            except ValueError:  # request line exceeded LineReader's limit
                await http_server.send_simple_response(
                    conn.s2s, HTTP_STATUS_BAD_REQUEST, b'text/html', b'request line too long')
                break
            if not request_line:  # EOF: the peer closed (cleanly or mid-line).
                break
            conn.state = 'busy'
            await http_server._handle_request(conn.s2s, conn.s2s, lines, request_line)
            conn.served += 1
            conn.last_done = milliseconds()
            await _settle_https()
    except Exception as e:
        if isinstance(e, OSError) and (
                'FATAL_ALERT' in str(e) or 'CONN_EOF' in str(e) or 'ECONNRESET' in str(e)
        ):
            logging.info('HTTPS client went away', 'main:_serve_https_conn')
        else:
            logging.exception('HTTPS client error', 'main:_serve_https_conn', e)
    finally:
        if conn.id in _https_live:
            del _https_live[conn.id]
        # Drop both references so the mbedTLS blocks become garbage, then collect: the
        # adjacent frees coalesce back into the original span for _restore_tls_reserve.
        try:
            conn.sock.close()
        except OSError:
            pass
        del conn.s2s, conn.sock
        gc.collect()
        await _settle_https()


async def serve_https(ssl_ctx):
    # Serve HTTPS on port 443 with as many concurrent connections as the heap can
    # hold.  Each wrapped socket holds ~22 KB of mbedTLS heap until it closes; on
    # the Pico W that is exactly one connection, so when a second client arrives its
    # wrap ENOMEMs and the idle-oldest live conn yields its span (it exits on its
    # own within one idle slice, then this same queued socket is wrapped).  On a
    # board with more heap (Pico 2) several wraps succeed and nothing is ever
    # evicted.  Either way a handshaken conn is held open for keep-alive: one
    # handshake (~1.3 s of crypto) carries unlimited later requests, which is what
    # makes the once-per-second status poll affordable.
    global _https_ssl_ctx
    if Stream is None:
        # CPython host debugging: no heap constraint, use the standard TLS server.
        await asyncio.start_server(http_server.serve_http_client, '0.0.0.0', 443, ssl=ssl_ctx)
        return
    _https_ssl_ctx = ssl_ctx
    try:
        addr_info = socket.getaddrinfo('0.0.0.0', 443)[0]
        s = socket.socket(addr_info[0])
        s.setblocking(False)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(addr_info[-1])
        s.listen(8)
    except OSError as e:
        logging.exception('could not start HTTPS server on port 443', 'main:serve_https', e)
        return
    while True:
        # MicroPython sockets are not awaitable: a non-blocking accept() with no
        # pending connection raises OSError immediately, so poll with a sleep.
        try:
            s2, addr = s.accept()
        except OSError:
            await asyncio.sleep(0.05)
        else:
            _https_pending.append((s2, addr))
            await _settle_https()


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

    web_port = safe_int(config.get('web_port') or DEFAULT_WEB_PORT, DEFAULT_WEB_PORT)
    if web_port < 0 or web_port > 65535:
        web_port = DEFAULT_WEB_PORT
        config['web_port'] = str(web_port)

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
    # served on port 443 when the convention-named cert/key files are present
    # and valid; in AP (setup) mode the hostname is not meaningful, so HTTPS
    # is never enabled there.
    logging.info('Starting web service on port 80', 'main:main')
    try:
        web_server = await asyncio.start_server(http_server.serve_http_client, '0.0.0.0', 80)
    except Exception as e:
        logging.exception('could not start web server on port 80', 'main:main', e)
        web_server = None

    https_server = None
    if ap_mode:
        logging.info('HTTPS disabled (AP mode)', 'main:main')
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
    #logging.loglevel = logging.INFO
    logging.loglevel = logging.DEBUG
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
