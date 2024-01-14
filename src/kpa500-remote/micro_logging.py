#
# micro_logging.py -- minimalistic logging for micropython.
# minimally compatible with python logging?
#
__author__ = 'J. B. Otterson'
__copyright__ = """
Copyright 2024, J. B. Otterson N1KDO.
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
__version__ = '0.0.1'

from utils import get_timestamp

DEBUG = 5
INFO = 4
WARNING = 3
ERROR = 2
CRITICAL = 1
NOTHING = 0

loglevel = ERROR


def _log(level: str, message: str, caller=None):
    if caller is None:
        print(f'{get_timestamp()} [{level}] {message}')
    else:
        print(f'{get_timestamp()} [{level}] [{caller}] {message}')


def debug(message, caller=None):
    if loglevel >= DEBUG:
        _log('DEBUG', message, caller)


def info(message, caller=None):
    if loglevel >= INFO:
        _log('INFO', message, caller)


def warning(message, caller=None):
    if loglevel >= WARNING:
        _log('WARNING', message, caller)


def error(message, caller=None):
    if loglevel >= ERROR:
        _log('ERROR', message, caller)


def critical(message, caller=None):
    if loglevel >= CRITICAL:
        _log('CRITICAL', message, caller)

