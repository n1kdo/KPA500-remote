#
# picow_network.py -- Raspberry Pi Pico W connect to Wifi Network.
# this is pulled out to it's own module because it is used widely.
#

__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2024, J. B. Otterson N1KDO.'
__version__ = '0.9.2'

#
# Copyright 2024, J. B. Otterson N1KDO.
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

from utils import upython

if upython:
    import machine
    import network
    import uasyncio as asyncio
    import micro_logging as logging
else:
    import asyncio
    import logging

import socket


class PicowNetwork:
    network_status_map = {
        network.STAT_IDLE: 'no connection and no activity',  # 0
        network.STAT_CONNECTING: 'connecting in progress',  # 1
        network.STAT_CONNECTING + 1: 'connected no IP address',  # 2, this is undefined, but returned.
        network.STAT_GOT_IP: 'connection successful',  # 3
        network.STAT_WRONG_PASSWORD: 'failed due to incorrect password',  # -3
        network.STAT_NO_AP_FOUND: 'failed because no access point replied',  # -2
        network.STAT_CONNECT_FAIL: 'failed due to other problems',  # -1
    }

    def __init__(self, config: dict, default_ssid='PICO-W', default_secret='PICO-W') -> None:
        self.keepalive = False
        self.ssid = config.get('SSID') or ''
        if len(self.ssid) == 0 or len(self.ssid) > 64:
            self.ssid = default_ssid
        self.secret = config.get('secret') or ''
        if self.secret is None or len(self.secret) == 0:
            self.secret = default_secret
        if len(self.secret) > 64:
            self.secret = self.secret[:64]

        self.hostname = config.get('hostname')
        if self.hostname is None or self.hostname == '':
            self.hostname = 'pico-w'

        self.access_point_mode = config.get('ap_mode', False)

        self.is_dhcp = config.get('dhcp', True)
        self.ip_address = config.get('ip_address')
        self.netmask = config.get('netmask')
        self.gateway = config.get('gateway')
        self.dns_server = config.get('dns_server')

        self.message='INIT'
        self.wlan = None

    async def connect(self):
        network.country('US')
        sleep = asyncio.sleep

        if self.access_point_mode:
            logging.info('Starting setup WLAN...', 'PicowNetwork:connect_to_network')
            self.wlan = network.WLAN(network.AP_IF)
            self.wlan.deinit()
            self.wlan.active(False)
            await sleep(1)

            self.wlan = network.WLAN(network.AP_IF)
            self.wlan.config(pm=self.wlan.PM_NONE)  # disable power save, this is a server.
            # wlan.deinit turns off the onboard LED because it is connected to the CYW43
            # turn it on again.
            onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
            onboard.on()

            try:
                logging.info(f'  setting hostname "{self.hostname}"', 'PicowNetwork:connect_to_network')
                network.hostname(self.hostname)
            except ValueError:
                logging.error('Failed to set hostname.', 'PicowNetwork:connect_to_network')

            #
            #define CYW43_AUTH_OPEN (0)                     ///< No authorisation required (open)
            #define CYW43_AUTH_WPA_TKIP_PSK   (0x00200002)  ///< WPA authorisation
            #define CYW43_AUTH_WPA2_AES_PSK   (0x00400004)  ///< WPA2 authorisation (preferred)
            #define CYW43_AUTH_WPA2_MIXED_PSK (0x00400006)  ///< WPA2/WPA mixed authorisation
            #

            if len(self.secret) == 0:
                security = 0
            else:
                security = 0x00400004  # CYW43_AUTH_WPA2_AES_PSK
            self.wlan.config(ssid=self.ssid, key=self.secret, security=security)
            self.wlan.active(True)
            logging.info(f'  wlan.active()={self.wlan.active()}', 'PicowNetwork:connect_to_network')
            logging.info(f'  ssid={self.wlan.config("ssid")}', 'PicowNetwork:connect_to_network')
            logging.info(f'  ifconfig={self.wlan.ifconfig()}', 'PicowNetwork:connect_to_network')
        else:
            logging.info('Connecting to WLAN...', 'PicowNetwork:connect_to_network')
            self.wlan = network.WLAN(network.STA_IF)
            self.wlan.disconnect()
            self.wlan.deinit()
            self.wlan.active(False)
            await sleep(1)
            # get a new one.
            self.wlan = network.WLAN(network.STA_IF)
            # wlan.deinit turns off the onboard LED because it is connected to the CYW43
            # turn it on again.
            onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
            onboard.on()
            try:
                logging.info(f'...setting hostname "{self.hostname}"', 'PicowNetwork:connect_to_network')
                network.hostname(self.hostname)
            except ValueError:
                logging.error('Failed to set hostname.', 'PicowNetwork:connect_to_network')
            self.wlan.active(True)
            self.wlan.config(pm=self.wlan.PM_NONE)  # disable power save, this is a server.

            if not self.is_dhcp:
                if self.ip_address is not None and self.netmask is not None and self.gateway is not None and self.dns_server is not None:
                    logging.info('...configuring network with static IP', 'PicowNetwork:connect_to_network')
                    self.wlan.ifconfig((self.ip_address, self.netmask, self.gateway, self.dns_server))
                    # TODO FIXME wlan.ifconfig is deprecated, "dns" parameter is not found in the doc
                    # https://docs.micropython.org/en/latest/library/network.html
                    # but it is not defined for the cyc43 on pico-w
                    #self.wlan.ipconfig(addr4=(self.ip_address, self.netmask),
                    #                   gw4=self.gateway,
                    #                   dns=self.dns_server)
                else:
                    logging.warning('Cannot use static IP, data is missing.', 'PicowNetwork:connect_to_network')
                    logging.warning('Configuring network with DHCP....', 'PicowNetwork:connect_to_network')
                    self.is_dhcp = True
            if self.is_dhcp:
                self.wlan.ipconfig(dhcp4=True)
                logging.info(f'...configuring network with DHCP {self.wlan.ifconfig()}', 'PicowNetwork:connect_to_network')
            else:
                logging.info(f'...configuring network with {self.wlan.ifconfig()}', 'PicowNetwork:connect_to_network')

            max_wait = 15
            # wl_status = self.wlan.status()
            logging.info(f'...connecting to "{self.ssid}"...', 'PicowNetwork:connect_to_network')
            self.wlan.connect(self.ssid, self.secret)
            last_wl_status = -9
            while max_wait > 0:
                wl_status = self.wlan.status()
                if wl_status != last_wl_status:
                    last_wl_status = wl_status
                    st = self.network_status_map.get(wl_status) or 'undefined'
                    logging.info(f'...network status: {wl_status} {st}', 'PicowNetwork:connect_to_network')
                if wl_status < 0 or wl_status >= 3:
                    break
                max_wait -= 1
                await sleep(1)
            if wl_status != network.STAT_GOT_IP:
                logging.warning(f'...network connect timed out: {wl_status}', 'PicowNetwork:connect_to_network')
                self.message = f'Error {wl_status} {st} '
                return None
            logging.info(f'...connected: {self.wlan.ifconfig()}', 'PicowNetwork:connect_to_network')

        onboard.on()  # turn on the LED, WAN is up.
        wl_config = self.wlan.ipconfig('addr4')  # get use str param name.
        ip_address = wl_config[0]
        self.message = f'AP {ip_address} ' if self.access_point_mode else f'{ip_address} '
        return

    def ifconfig(self):
        return self.wlan.ifconfig()

    def status(self):
        keys = ['antenna',
                'channel',
                'hostname',
                # 'hidden',
                # 'key',
                'mac',
                'pm',
                # 'secret',
                'security',
                'ssid',
                # 'reconnects',
                'txpower']
        # note that there is also 'trace' and 'monitor' that appear to be write-only

        if self.wlan is not None:
            for k in keys:
                try:
                    data = self.wlan.config(k)
                    if isinstance(data, str):
                        logging.info(f'WLAN.config("{k}")="{data}"', 'PicowNetwork:status')
                    elif isinstance(data, int):
                        logging.info(f'WLAN.config("{k}")={data}', 'PicowNetwork:status')
                    elif isinstance(data, bytes):
                        mac = ':'.join([f'{b:02x}' for b in data])
                        logging.info(f'WLAN.config("{k}")={mac}', 'PicowNetwork:status')
                    else:
                        logging.info(f'WLAN.config("{k}")={data} {type(data)}', 'PicowNetwork:status')

                except Exception as exc:
                    logging.warning(f'{exc}: "{k}"', 'PicowNetwork:status')
        else:
            logging.warning('Network not initialized.', 'PicowNetwork:status')

    def is_connected(self):
        return self.wlan.isconnected() if self.wlan is not None else False

    def has_wan(self):
        if not self.is_connected():
            return False
        test_host = 'www.google.com'
        try:
            addr = socket.getaddrinfo(test_host, 80)
            if addr is not None and len(addr) > 0:
                addr = addr[0][4][0]
            else:
                return False
        except Exception as exc:
            logging.error(f'cannot lookup {test_host}: {exc}')
            return False
        logging.info(f'has_wan found IP {addr}')
        return True

    def has_router(self):
        if not self.is_connected():
            return False
        s = None
        try:
            router_ip = self.wlan.ifconfig()[2]
            addr = socket.getaddrinfo(router_ip, 80)[0][-1]
            s = socket.socket()
            s.connect(addr)
            s.send(b'GET / HTTP/1.1\r\n\r\n')
            data = s.recv(128)
            if data is not None and len(data) > 0:
                # print(f'got some data: "{str(data)}".')
                return True
        except Exception as exc:
            logging.error(f'cannot lookup or connect to router: {exc}')
            return False
        finally:
            if s is not None:
                s.close()
                s = None

    async def keep_alive(self):
        self.keepalive = True
        # eliminate >1 dict lookup
        sleep = asyncio.sleep
        while self.keepalive:
            connected = self.is_connected()
            logging.debug(f'self.is_connected() = {self.is_connected()}','PicowNetwork.keepalive')
            if not connected:
                logging.warning('not connected...  attempting network connect...', 'PicowNetwork:keep_alive')
                await self.connect()
            else:
                logging.debug(f'connected = {connected}', 'PicowNetwork.keepalive')
            await sleep(5)  # check network every 5 seconds
        logging.info('keepalive exit', 'PicowNetwork.keepalive loop exit.')

    def get_message(self):
        return self.message

