"""
watchdog processor for micropython IOT projects.
1. set up the watchdog.
2. periodically reset the watchdog.
"""

__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2025 J. B. Otterson N1KDO.'
__version__ = '0.0.1'

#
# Copyright 2025, J. B. Otterson N1KDO.
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

import asyncio
from machine import WDT

class Watchdog:
    __slots__ = ('_wdt', '_period')

    def __init__(self, threshold:int=5000, period:int=1000)->None:
        """
        :param threshold: watchdog timeout in milliseconds, default 5000ms
        :param period: feed period in milliseconds, default 1000ms
        """
        if period >= threshold:
            raise ValueError('period must be less than threshold')
        self._period = period
        self._wdt = WDT(timeout=threshold)
        asyncio.create_task(self._feeder())

    async def _feeder(self):
        feed = self._wdt.feed
        period = self._period  # Cache period
        asleep = asyncio.sleep_ms  # Cache sleep function

        while True:
            feed()
            await asleep(period)
