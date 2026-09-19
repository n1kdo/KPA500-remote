#
# config_data.py -- KPA500 remote configuration data class.
#

__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2026 J. B. Otterson N1KDO.'
__version__ = '0.0.2'  # 2026-09-01

#
# Copyright 2026 J. B. Otterson N1KDO.
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

from cached_config_data import CachedConfigData

CONFIG_FILE = 'data/config.json'

# noinspection SpellCheckingInspection
DEFAULT_SECRET = 'elecraft'
DEFAULT_SSID = 'kpa500'
DEFAULT_KPA500_TCP_PORT = 4626
DEFAULT_KAT500_TCP_PORT = 4627
DEFAULT_WEB_PORT = 80


class ConfigData(CachedConfigData):
    def __init__(self):
        super().__init__(CONFIG_FILE)

    @staticmethod
    def _default_config_data():
        return {
            'SSID': DEFAULT_SSID,
            'secret': DEFAULT_SECRET,
            'username': 'admin',
            'password': 'admin',
            'dhcp': True,
            'hostname': 'kpa500',
            'ip_address': '192.168.1.73',
            'netmask': '255.255.255.0',
            'gateway': '192.168.1.1',
            'dns_server': '8.8.8.8',
            'kpa_tcp_port': DEFAULT_KPA500_TCP_PORT,
            'kat_tcp_port': DEFAULT_KAT500_TCP_PORT,
            'web_port': DEFAULT_WEB_PORT,
}
