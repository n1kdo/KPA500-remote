#
# serial port listener for protocol reverse engineering.
#
# listens on com3 for traffic from HOST to DUT
# listens on com4 for traffic from DUT to HOST
#
import logging
import serial
import sys
import time

BAUD_RATE = 38400

kat500_data = {}


key_names = (
    'amp::button::OPER'            # 00
    'amp::button::STBY'            # 01
    'amp::button::CLEAR'           # 02
    'amp::button::SPKR'            # 03
    'amp::button::PWR'             # 04
    'amp::dropdown::Band'          # 05
    'amp::fault'                   # 06
    'amp::firmware'                # 07
    'amp::list::Band'              # 08
    'amp::meter::Current'          # 09
    'amp::meter::Power'            # 10
    'amp::meter::SWR'              # 11
    'amp::meter::Temp'             # 12
    'amp::meter::Voltage'          # 13
    'amp::range::Fan Speed'        # 14
    'amp::range::PWR Meter Hold'   # 15
    'amp::serial'                  # 16
    'amp::slider::Fan Speed'       # 17
    'amp::slider::PWR Meter Hold'  # 18
)

'''
raw key/value data:

'server::login': 'valid'
'server::login::invalid: 'Invalid password provided. Remote control will not be allowed.'
'server::login::invalid: 'Invalid username provided. Remote control will not be allowed.'

'amp::firmware': '01.54'
'amp::serial': '868'
'amp::fault': 'AMP ON'
'amp::button::OPER': '1'
'amp::button::STBY': '0'
'amp::button::CLEAR': '0'
'amp::button::SPKR': '1'
'amp::button::PWR': '1'
'amp::list::Band': '160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m'
'amp::dropdown::Band': '12m'
'amp::meter::Current': '000'
'amp::meter::Power': '000'
'amp::meter::SWR': '000'
'amp::meter::Temp': '040'
'amp::meter::Voltage': '731'
'amp::range::Fan Speed': '0,6,0'
'amp::range::PWR Meter Hold': '0,10,0'
'amp::slider::Fan Speed': '0'
'amp::slider::PWR Meter Hold': '4'

also:

server::login::admin::admin for login
gets back
server::login::valid

amp::button::OPER::1



more:

server::login::
amp::button::
amp::dropdown::
amp::slider::

amp::info::
amp::firmware::
amp::fault::
amp::serial::
amp::status::
amp::range::
amp::meter::
amp::message::
amp::list::
amp::bug::

server::login::valid
server::login::invalid::Invalid password provided. Remote control will not be allowed.
server::login::invalid::Invalid username provided. Remote control will not be allowed.


'''


def buffer_to_hexes(buffer):
    return ' '.join('{:02x}'.format(b) for b in buffer)


def hexdump_buffer(buffer):
    result = ''
    hex_bytes = ''
    printable = ''
    offset = 0
    ofs = '{:04x}'.format(offset)
    for b in buffer:
        hex_bytes += '{:02x} '.format(b)
        printable += chr(b) if 32 <= b <= 126 else '.'
        offset += 1
        if len(hex_bytes) >= 48:
            result += ofs + '  ' + hex_bytes + '  ' + printable + '\n'
            hex_bytes = ''
            printable = ''
            ofs = '{:04x}'.format(offset)
    if len(hex_bytes) > 0:
        hex_bytes += ' ' * 47
        hex_bytes = hex_bytes[0:47]
        result += ofs + '  ' + hex_bytes + '   ' + printable + '\n'
    return result


def dump_buffer(name, buffer, dump_all=False):
    if len(buffer) < 5:
        dump_all = True
    if dump_all:
        print('{} message {}'.format(name, buffer_to_hexes(buffer)))
    else:
        print('{} payload {}'.format(name, buffer_to_hexes(buffer[2:-2])))


interesting_messages_3 = ('^BN', '^FL', '^OS', '^TM')
band_number_to_name = {0: '160m', 1: '80m', 2: '60m', 3: '40m', 4: '30m',
                       5: '20m', 6: '17m', 7: '15m', 8: '12m', 9: '10m', 10: '6m', }


def parse_kat500_message(message):
    global kat500_data
    if message is None or message == '':
        print('invalid message: empty.')
        return
    message = message.upper()
    if message[-1] != ';':
        print('invalid message: no terminator')
    print(f'"{message}"', end=' : ')
    if message == ';':
        print('NULL message.')
        return
    message = message[0:-1]  # remove terminator
    lm = len(message)
    if lm >= 5:  # check for 5 letter message names
        fragment = message[0:5]
        # print(f'fragment "{fragment}"')
        if fragment == 'VSWRB':
            data = message[5:]
            if lm > 5:
                print(f'Bypass VSWR is {data}')
            else:
                print('Query Bypass VSWR')
            return
    if lm >= 4:  # check for 4 letter message names. AMPI ATTN VFWD VRFL VSWR
        fragment = message[0:4]
        # print(f'fragment "{fragment}"')
        if lm > 4:
            data = message[4:]
        else:
            data = None
        if fragment == 'AMPI':
            if data is None:
                print('Amplifier Interrupt Keyline Query')
            else:
                print(f'Amplifier Key Line Interrupt {data}')
            return
        if fragment == 'ATTN':
            if data is None:
                print('Attenuator Query')
            else:
                print(f'Attenuator {data}')
            return
        if fragment == 'VFWD':
            if data is None:
                print('Forward ADC Query')
            else:
                print(f'Forward ADC {data}')
            return
        if fragment == 'VRFL':
            if data is None:
                print('Reverse ADC Query')
            else:
                print(f'Reverse ADC {data}')
            return
        if fragment == 'VSWR':
            if data is None:
                print('VSWR Query')
            else:
                print(f'VSWR {data}')
            return
    if lm >= 3:  # check for 3 letter message names. BYP FLT
        fragment = message[0:3]
        # print(f'fragment "{fragment}"')
        if lm > 3:
            data = message[3:]
        else:
            data = None
        if fragment == 'BYP':
            if data is None:
                print('Bypass Query')
            else:
                print(f'Bypass {data}')
            return
        if fragment == 'FLT':
            if data is None:
                print('Fault Query')
            else:
                print(f'Fault {data}')
            return
    if lm >= 2:  # check for 2 letter message names. AN BN MD PS RV SN TP
        fragment = message[0:2]
        # print(f'fragment "{fragment}"')
        if lm > 3:
            data = message[2:]
        else:
            data = None
        if fragment == 'AN':
            if data is None:
                print('Antenna Query')
            else:
                print(f'Antenna {data}')
            return
        if fragment == 'BN':
            if data is None:
                print('Band Number Query')
            else:
                print(f'Band Number {data}')
            return
        if fragment == 'MD':
            if data is None:
                print('Mode Query')
            else:
                print(f'Mode {data}')
            return
        if fragment == 'PS':
            if data is None:
                print('Power Query')
            else:
                print(f'Power {data}')
            return
        if fragment == 'RV':
            if data is None:
                print('Revision Query')
            else:
                print(f'Revision {data}')
            return
        if fragment == 'SN':
            if data is None:
                print('Serial Number Query')
            else:
                print(f'Serial Number {data}')
            return
        if fragment == 'TP':
            if data is None:
                print('Tune Poll Query')
            else:
                print(f'Tune Poll {data}')
            return
    if lm >= 1:  # check for 1 letter message names. F
        fragment = message[0:1]
        # print(f'fragment "{fragment}"')
        if lm > 1:
            data = message[1:]
        else:
            data = None
        if fragment == 'F':
            if data is None:
                print('Frequency Query')
            else:
                print(f'Frequency {data}')
            return
    print(f'***** unhandled: {message} *****')


def main():
    try:
        tx_port = serial.Serial(port='com3:',
                                baudrate=BAUD_RATE,
                                parity=serial.PARITY_NONE,
                                bytesize=serial.EIGHTBITS,
                                stopbits=serial.STOPBITS_ONE,
                                timeout=0)
        rx_port = serial.Serial(port='com4:',
                                baudrate=BAUD_RATE,
                                parity=serial.PARITY_NONE,
                                bytesize=serial.EIGHTBITS,
                                stopbits=serial.STOPBITS_ONE,
                                timeout=0)

        while True:
            while True:
                buf = tx_port.read(32)
                if buf is not None and len(buf) > 0:
                    msecs = time.time() * 1000
                    print(f'{msecs} TX: {buf.decode()}')
                    data = buf.decode().split(';')
                    for msg in data:
                        if msg != '':
                            parse_kat500_message(msg + ';')
                    # print(hexdump_buffer(buf))
                else:
                    break
            while True:
                buf = rx_port.read(32)
                if buf is not None and len(buf) > 0:
                    msecs = time.time() * 1000
                    print(f'{msecs} RX: {buf.decode()}')
                    data = buf.decode().split(';')
                    for msg in data:
                        if msg != '':
                            parse_kat500_message(msg + ';')
                    # parse_kat500_message(buf.decode())
                    # print(hexdump_buffer(buf))
                else:
                    break
            time.sleep(0.02)

    except IOError as e:
        print(e)


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:{}',
                        level=logging.INFO,
                        stream=sys.stdout)
    logging.Formatter.converter = time.gmtime
    main()
