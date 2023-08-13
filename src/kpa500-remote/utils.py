import sys
import time

upython = sys.implementation.name == 'micropython'


def get_timestamp(tt=None):
    if tt is None:
        tt = time.gmtime()
    return f'{tt[0]:04d}-{tt[1]:02d}-{tt[2]:02d} {tt[3]:02d}:{tt[4]:02d}:{tt[5]:02d}Z'


def milliseconds():
    if upython:
        return time.ticks_ms()
    return int(time.time() * 1000)


def safe_int(value, default=-1):
    if isinstance(value, int):
        return value
    return int(value) if value.isdigit() else default

