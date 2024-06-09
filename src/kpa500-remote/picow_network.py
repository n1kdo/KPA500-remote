#
# picow_network.py -- Raspberry Pi Pico W connect to Wifi Network.
# this is pulled out to it's own module because it is used widely.
#

__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2024, J. B. Otterson N1KDO.'

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

import time
from utils import upython

if upython:
    import machine
    import network
    import micro_logging as logging


def connect_to_network(config, default_ssid='PICO-W', default_secret='PICO-W', morse_code_sender=None):
    network_status_map = {
        network.STAT_IDLE: 'no connection and no activity',  # 0
        network.STAT_CONNECTING: 'connecting in progress',  # 1
        network.STAT_CONNECTING + 1: 'connected no IP address',  # 2, this is undefined, but returned.
        network.STAT_GOT_IP: 'connection successful',  # 3
        network.STAT_WRONG_PASSWORD: 'failed due to incorrect password',  # -3
        network.STAT_NO_AP_FOUND: 'failed because no access point replied',  # -2
        network.STAT_CONNECT_FAIL: 'failed due to other problems',  # -1
    }

    network.country('US')
    ssid = config.get('SSID') or ''
    if len(ssid) == 0 or len(ssid) > 64:
        ssid = default_ssid
    secret = config.get('secret') or ''
    if len(secret) > 64:
        secret = secret[:64]

    hostname = config.get('hostname')
    if hostname is None or hostname == '':
        hostname = 'pico-w'

    access_point_mode = config.get('ap_mode') or False
    if access_point_mode:
        logging.info('Starting setup WLAN...', 'main:connect_to_network')
        wlan = network.WLAN(network.AP_IF)
        wlan.deinit()
        wlan = network.WLAN(network.AP_IF)
        wlan.config(pm=wlan.PM_NONE)  # disable power save, this is a server.
        # wlan.deinit turns off the onboard LED because it is connected to the CYW43
        # turn it on again.
        onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
        onboard.on()


        try:
            logging.info(f'  setting hostname "{hostname}"', 'main:connect_to_network')
            network.hostname(hostname)
        except ValueError:
            logging.error('Failed to set hostname.', 'main:connect_to_network')

        #
        #define CYW43_AUTH_OPEN (0)                     ///< No authorisation required (open)
        #define CYW43_AUTH_WPA_TKIP_PSK   (0x00200002)  ///< WPA authorisation
        #define CYW43_AUTH_WPA2_AES_PSK   (0x00400004)  ///< WPA2 authorisation (preferred)
        #define CYW43_AUTH_WPA2_MIXED_PSK (0x00400006)  ///< WPA2/WPA mixed authorisation
        #
        ssid = default_ssid
        secret = default_secret
        if len(secret) == 0:
            security = 0
        else:
            security = 0x00400004  # CYW43_AUTH_WPA2_AES_PSK
        wlan.config(ssid=ssid, key=secret, security=security)
        wlan.active(True)
        logging.info(f'  wlan.active()={wlan.active()}', 'main:connect_to_network')
        logging.info(f'  ssid={wlan.config("ssid")}', 'main:connect_to_network')
        logging.info(f'  ifconfig={wlan.ifconfig()}', 'main:connect_to_network')
    else:
        logging.info('Connecting to WLAN...', 'main:connect_to_network')
        wlan = network.WLAN(network.STA_IF)
        wlan.deinit()
        wlan = network.WLAN(network.STA_IF)
        # wlan.deinit turns off the onboard LED because it is connected to the CYW43
        # turn it on again.
        onboard = machine.Pin('LED', machine.Pin.OUT, value=0)
        onboard.on()
        try:
            logging.info(f'...setting hostname "{hostname}"', 'main:connect_to_network')
            network.hostname(hostname)
        except ValueError:
            logging.error('Failed to set hostname.', 'main:connect_to_network')
        wlan.active(True)
        wlan.config(pm=wlan.PM_NONE)  # disable power save, this is a server.

        logging.info(f'...ifconfig={wlan.ifconfig()}', 'main:connect_to_network')
        is_dhcp = config.get('dhcp')
        if is_dhcp is None:
            is_dhcp = True
        if not is_dhcp:
            ip_address = config.get('ip_address')
            netmask = config.get('netmask')
            gateway = config.get('gateway')
            dns_server = config.get('dns_server')
            if ip_address is not None and netmask is not None and gateway is not None and dns_server is not None:
                logging.info('Configuring network with static IP', 'main:connect_to_network')
                wlan.ifconfig((ip_address, netmask, gateway, dns_server))
            else:
                logging.warning('Cannot use static IP, data is missing.', 'main:connect_to_network')
                logging.warning('Configuring network with DHCP....', 'main:connect_to_network')
                is_dhcp = True
                # wlan.ifconfig('dhcp')
        if is_dhcp:
            logging.info('Configuring network with DHCP...', 'main:connect_to_network')

        max_wait = 15
        wl_status = wlan.status()
        logging.info(f'...ifconfig={wlan.ifconfig()}', 'main:connect_to_network')
        logging.info(f'...connecting to "{ssid}"...', 'main:connect_to_network')
        wlan.connect(ssid, secret)
        while max_wait > 0:
            wl_status = wlan.status()
            st = network_status_map.get(wl_status) or 'undefined'
            logging.info(f'...network status: {wl_status} {st}', 'main:connect_to_network')
            if wl_status < 0 or wl_status >= 3:
                break
            max_wait -= 1
            time.sleep(1)
        if wl_status != network.STAT_GOT_IP:
            logging.error('Network did not connect!', 'main:connect_to_network')
            if morse_code_sender is not None:
                morse_code_sender.set_message('ERR ')
            return None, None
        logging.info(f'...connected, ifconfig={wlan.ifconfig()}', 'main:connect_to_network')

    onboard.on()  # turn on the LED, WAN is up.
    wl_config = wlan.ifconfig()
    ip_address = wl_config[0]
    message = f'AP {ip_address} ' if access_point_mode else f'{ip_address} '
    message = message.replace('.', ' ')
    if morse_code_sender is not None:
        morse_code_sender.set_message(message)
        logging.info(f'setting morse code message to {message}', 'main:connect_to_network')
    return ip_address
