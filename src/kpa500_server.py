#
#
#
from serialport import SerialPort
from time import sleep
port = None

kpa500_data = [' '] * 19
kpa500_updated = []
kpa500_command_queue = []

band_number_to_name = ('160m', '80m', '60m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m')

key_names = (
    'amp::button::OPER',            # 00
    'amp::button::STBY',            # 01
    'amp::button::CLEAR',           # 02
    'amp::button::SPKR',            # 03
    'amp::button::PWR',             # 04
    'amp::dropdown::Band',          # 05
    'amp::fault',                   # 06
    'amp::firmware',                # 07
    'amp::list::Band',              # 08
    'amp::meter::Current',          # 09
    'amp::meter::Power',            # 10
    'amp::meter::SWR',              # 11
    'amp::meter::Temp',             # 12
    'amp::meter::Voltage',          # 13
    'amp::range::Fan Speed',        # 14
    'amp::range::PWR Meter Hold',   # 15
    'amp::serial',                  # 16
    'amp::slider::Fan Speed',       # 17
    'amp::slider::PWR Meter Hold',  # 18
)
kpa500_data[2] = '0'
kpa500_data[8] = '160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m'
kpa500_data[14] = '0,6,0'
kpa500_data[15] = '0,10,0'
kpa500_data[18] = '4'


def kpa500_send_receive(port, message, buffer):
    port.write(message)
    sleep(0.05)
    bytes_read = port.readinto(buffer)
    return bytes_read


def update_kpa500_data(index, value):
    global kpa500_data, kpa500_updated
    if kpa500_data[index] != value:
        kpa500_data[index] = value
        kpa500_updated.append(index)


def process_kpa500_message(buffer, bytes_read):
    if bytes_read < 1:
        return
    if buffer[0] != ord('^'):
        print('what?')
        return
    cmdlen = 3  # including the ^
    if buffer[cmdlen] > 57:  # there is another letter
        cmdlen = 4

    cmd = buffer[1:cmdlen].decode()
    semi_offset = buffer.find(b';')
    cmd_data = buffer[cmdlen:semi_offset].decode()

    print(cmd, cmd_data)

    if cmd == 'BN':  # band
        band_num = int(cmd_data)
        if band_num <= 10:
            band_name = band_number_to_name[band_num]
            update_kpa500_data(5, band_name)
    elif cmd == 'FC':  # fan minimum speed
        fan_min = int(cmd_data)
        update_kpa500_data(17, str(fan_min))
    elif cmd == 'FL':
        if cmd_data == '00':
            fault = 'AMP ON'
        else:
            fault = cmd_data
        update_kpa500_data(6, fault)
    elif cmd == 'ON':
        update_kpa500_data(4, cmd_data)
    elif cmd == 'OS':
        oper = cmd_data
        stby = '1' if cmd_data == '0' else '0'
        update_kpa500_data(0, oper)
        update_kpa500_data(1, stby)
    elif cmd == 'RVM':  # version
        update_kpa500_data(7, cmd_data)
    elif cmd == 'SN':  # serial number
        update_kpa500_data(16, cmd_data)
    elif cmd == 'SP':  # speaker on/off
        update_kpa500_data(3, cmd_data)
    elif cmd == 'TM':  # temp
        update_kpa500_data(12, cmd_data)
    elif cmd == 'VI':  # volts
        split_cmd_data = cmd_data.split(' ')
        if len(split_cmd_data) == 2:
            volts = split_cmd_data[0]
            amps = split_cmd_data[1]
            update_kpa500_data(13, volts)
            update_kpa500_data(9, amps)
    elif cmd == 'WS':  # watts swr
        split_cmd_data = cmd_data.split(' ')
        if len(split_cmd_data) == 2:
            watts = split_cmd_data[0]
            swr = split_cmd_data[1]
            update_kpa500_data(10, watts)
            update_kpa500_data(11, swr)
    else:
        print(f'unprocessed command {cmd} with data {cmd_data}')


def kpa500_server(amp_serial_port):
    global kpa500_command_queue

    buffer = bytearray(16)
    amp_found = False
    tries = 3
    while not amp_found and tries > 0:
        # gently poke the amplifier -- is it connected?
        bytes_read = kpa500_send_receive(amp_serial_port, b';', buffer)
        # connected will return a ';' here
        if bytes_read != 1 or buffer[0] != 59:
            print(f'amp not found, {tries} tries left...')
            tries -= 1
            print(f'amp not found, {tries} tries left...')
        else:
            amp_found = True
    if not amp_found:
        print('amp not found.')
        return

    amp_on = False
    while not amp_on:
        # check to see if amp is on or off
        bytes_read = kpa500_send_receive(amp_serial_port, b'I', buffer)
        if bytes_read > 0:
            if buffer[:bytes_read].decode() == 'KPA500\r\n':
                print('amp is off')
                # amp is off, try to turn it on...
                bytes_read = kpa500_send_receive(amp_serial_port, b'P', buffer)
        else:
            amp_on = True

    initial_queries = (b';',      # attention!
                       b'^RVM;',  # get version
                       b'^SN;',   # Serial Number
                       b'^ON;',   # on/off status
                       b'^FC;')   # minimum fan speed.
    for query in initial_queries:
        bytes_read = kpa500_send_receive(amp_serial_port, query, buffer)
        if bytes_read > 0:
            process_kpa500_message(buffer, bytes_read)
        else:
            if len(query) > 1:
                print(f'no response to {query}!')
        sleep(0.1)

    normal_queries = (b'^FL;',  # faults
                      b'^WS;',  # watts/swr
                      b'^VI;',  # volts/amps
                      b'^OS;',  # standby/operate
                      b'^TM;',  # temperature
                      b'^BN;',  # band
                      b'^SP;',  # speaker
                      )

    while True:
        for query in normal_queries:
            # first check to see if there are any commands queued to be sent to the amp...
            if len(kpa500_command_queue) > 0:
                # there is at least one command queued
                send_command = kpa500_command_queue.pop(0)
                bytes_read = kpa500_send_receive(amp_serial_port, send_command, buffer)
                if bytes_read > 0:
                    process_kpa500_message(buffer, bytes_read)
            # send the next query to the amp.
            bytes_read = kpa500_send_receive(amp_serial_port, query, buffer)
            if bytes_read > 0:
                process_kpa500_message(buffer, bytes_read)
            else:
                print(f'no response to {query}!')
            sleep(0.1)


def main():
    global port

    try:
        port = SerialPort(baudrate=38400, timeout=0)
        kpa500_server(port)
    except Exception as ex:
        print(ex)
    for i in range(len(kpa500_data)):
        print(f'{key_names[i]} : {kpa500_data[i]} ')


if __name__ == "__main__":
    main()
