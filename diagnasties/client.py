# stuff

import socket
import time

kpa500_remote_ip_hostname = '192.168.1.102'
kpa500_remote_port = 4626
kpa500_remote_username = 'admin'
kpa500_remote_password = 'admin'
kpa500_status = {}


def parse_kpa500_message(buffer, size):
    global kpa500_status
    if size == 0:
        return
    msg = buffer[0:size].decode()
    lines = msg.split('\n')
    for line in lines:
        value_offset = line.rfind('::')
        if value_offset > 0:
            key = line[:value_offset]
            value = line[value_offset+2:]
            old_value = kpa500_status.get(key)

            kpa500_status[key] = value
            print(f'setting {key} to {value} (was {old_value})')


def main():
    global kpa500_status

    try:
        ip_addr = socket.gethostbyname(kpa500_remote_ip_hostname)
        print(ip_addr)
    except socket.gaierror:
        print('could not look up host')
        return False

    try:
        try:
            skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print("Socket successfully created")
        except socket.error as err:
            print("socket creation failed with error %s" % err)
            return False

        skt.connect((ip_addr, kpa500_remote_port))

        buffer = bytearray(1024)

        # create login message
        cmd = f'server::login::{kpa500_remote_username}::{kpa500_remote_password}\n'
        # send login message
        print(f'TX: {cmd}')
        skt.send(cmd.encode())

        # wait for response
        num_received = skt.recv_into(buffer)
        print(f'RX: {buffer[:num_received].decode()}')
        parse_kpa500_message(buffer, num_received)
        if kpa500_status.get('server::login') != 'valid':
            print('server login failed.')
        else:
            print('connected to server')
        print('---')

        # wait for response
        num_received = skt.recv_into(buffer)
        print(f'RX: {buffer[:num_received].decode()}')
        parse_kpa500_message(buffer, num_received)

        while True:
            num_received = skt.recv_into(buffer)
            if num_received:
                message = buffer[:num_received].decode()
                message = message.replace('\n', '\\n')
                print(f'RX: {message}')
            parse_kpa500_message(buffer, num_received)
    except KeyboardInterrupt as ke:
        skt.close()

    for k, v in kpa500_status.items():
        print(f"'{k}': '{v}'")


if __name__ == "__main__":
    main()
