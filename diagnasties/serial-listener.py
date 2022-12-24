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

kpa500_data = {}


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
            result += ofs + '  ' + hex_bytes + '  ' + printable +'\n'
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


def parse_kpa500_message(message):
    global kpa500_data
    message = message.upper()
    if len(message) == 1:
        if message == 'I':
            print('[I]nfo request (boot mode)')
        elif message == 'P':
            print('[P]ower on request (boot mode)')
        elif message == ';':
            print('empty message (;)')
        return False
    elif len(message) < 3:
        print(f'"{message}" is too short at {len(message)}')
        return False
    if message[0] != '^':
        print(f'no leading caret, "{message}"')
        return False
    print(f'"{message}"', end=' : ')
    three_bytes = message[0:3]
    if three_bytes == '^BN':  # band selection
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            kpa500_data['amp::dropdown::Band'] = band_number_to_name[int(data)]
        else:
            print('Band enquiry')
    elif three_bytes == '^FL':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            print(f'Faults {int(data)}')
        else:
            print('Faults enquiry')
    elif three_bytes == '^ON':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            power_state = int(data)
            print(f'ON/OFF {power_state}')
            kpa500_data['amp::button::PWR'] = data
            return
        else:
            print('ON/OFF set to OFF (empty data) or enquiry')
    elif three_bytes == '^OS':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            i = int(data)
            print(f'Standby i')
            if i == 0:
                kpa500_data['amp::button::STBY'] = '1'
                kpa500_data['amp::button::OPER'] = '0'
        else:
            print('Standby enquiry')
    elif three_bytes == '^SN':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            serial_number = int(data)
            kpa500_data['amp::serial'] = serial_number
            print(data)
        else:
            print('Serial Number enquiry')
    elif three_bytes == '^SP':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            kpa500_data['amp::button::SPKR'] = data
        else:
            print('Speaker enquiry')
    elif three_bytes == '^TM':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            kpa500_data['amp::meter::Temp'] = data
        else:
            print('Temperature enquiry')
    elif three_bytes == '^VI':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            stuff = data.split(' ')
            kpa500_data['amp::meter::Voltage'] = stuff[0]
            kpa500_data['amp::meter::Current'] = stuff[1]
        else:
            print('Volts/Amps enquiry')
    elif three_bytes == '^WS':
        sp = message.find(';')
        data = message[3:sp]
        if len(data) > 0:
            stuff = data.split(' ')
            kpa500_data['amp::meter::Power'] = stuff[0]
            kpa500_data['amp::meter::SWR'] = stuff[1]
        else:
            print('Watts enquiry')
    else:
        four_bytes = message[0:4]
        if four_bytes == '^RVM':
            sp = message.find(';')
            data = message[4:sp]
            if len(data) > 0:
                kpa500_data['amp::firmware'] = data
            else:
                print('Version enquiry')
        else:
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
                    pass
                    print(f'TX: {buf.decode()}')
                    #parse_kpa500_message(buf.decode())
                    #print(f'transmit: "{buf.decode()}"')
                    #print(hexdump_buffer(buf))
                else:
                    break
            while True:
                buf = rx_port.read(32)
                if buf is not None and len(buf) > 0:
                    #print(f'receive: "{buf.decode()}')
                    print(f'RX: {buf.decode()}')
                    #parse_kpa500_message(buf.decode())
                    #print(hexdump_buffer(buf))
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
