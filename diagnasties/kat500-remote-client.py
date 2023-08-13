# stuff

import socket

kat500_remote_ip_hostname = '192.168.1.102'
kat500_remote_port = 4627
kat500_remote_username = 'admin'
kat500_remote_password = 'admin'
kat500_status = {}


def parse_kat500_message(buffer, size):
    global kat500_status
    if size == 0:
        return
    msg = buffer[0:size].decode()
    lines = msg.split('\n')
    for line in lines:
        value_offset = line.rfind('::')
        if value_offset > 0:
            key = line[:value_offset]
            value = line[value_offset+2:]
            old_value = kat500_status.get(key)

            kat500_status[key] = value
            print(f'setting {key} to {value} (was {old_value})')


def main():
    global kat500_status
    skt = None

    try:
        ip_addr = socket.gethostbyname(kat500_remote_ip_hostname)
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

        skt.connect((ip_addr, kat500_remote_port))

        buffer = bytearray(1024)

        # create login message
        cmd = f'server::login::{kat500_remote_username}::{kat500_remote_password}\n'
        # send login message
        print(f'TX: {cmd}')
        skt.send(cmd.encode())

        # wait for response
        num_received = skt.recv_into(buffer)
        print(f'RX: {buffer[:num_received].decode()}')
        parse_kat500_message(buffer, num_received)
        if kat500_status.get('server::login') != 'valid':
            print('server login failed.')
        else:
            print('connected to server')
        print('---')

        # wait for response
        num_received = skt.recv_into(buffer)
        # print(f'RX: {buffer[:num_received].decode()}')
        parse_kat500_message(buffer, num_received)

        while True:
            num_received = skt.recv_into(buffer)
            if num_received > 1:
                message = buffer[:num_received].decode()
                message = message.replace('\n', '\\n')
                print(f'RX: {message} {num_received}')
                parse_kat500_message(buffer, num_received)
    except KeyboardInterrupt:
        if skt is not None:
            skt.close()

    print('\n\n')
    keys = sorted(kat500_status.keys())
    for k in keys:
        print(f"'{k}': '{kat500_status[k]}'")
    print(f'Found {len(k)} keys')


if __name__ == "__main__":
    main()
