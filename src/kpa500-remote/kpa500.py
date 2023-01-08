#
# KPA500 & KPA-500 Remote client data abstraction
#


class ClientData:
    """
    class holds data for each KPA500-Remote (Elecraft) client.
    """
    def __init__(self, client_name):
        self.client_name = client_name
        self.update_list = []
        self.authorized = False
        self.connected = True
        self.last_receive = 0
        self.last_send = 0


class KPA500:
    band_number_to_name = ('160m', '80m', '60m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m')
    # noinspection SpellCheckingInspection
    key_names = (
        b'amp::button::OPER',            # 00 : 0 or 1
        b'amp::button::STBY',            # 01 : 0 or 1
        b'amp::button::CLEAR',           # 02 : 0 or 1
        b'amp::button::SPKR',            # 03 : 0 or 1
        b'amp::button::PWR',             # 04 : 0 or 1
        b'amp::dropdown::Band',          # 05 : string
        b'amp::fault',                   # 06 : string
        b'amp::firmware',                # 07 : string
        b'amp::list::Band',              # 08 : string
        b'amp::meter::Current',          # 09 : integer
        b'amp::meter::Power',            # 10 : integer
        b'amp::meter::SWR',              # 11 : integer
        b'amp::meter::Temp',             # 12 : integer
        b'amp::meter::Voltage',          # 13 : integer
        b'amp::range::Fan Speed',        # 14 : string
        b'amp::range::PWR Meter Hold',   # 15 : string
        b'amp::serial',                  # 16 : string
        b'amp::slider::Fan Speed',       # 17 : integer
        b'amp::slider::PWR Meter Hold',  # 18 : integer
    )

    fault_texts = ('AMP ON',    # 0
                   '01',        # 1
                   'HI CURR',   # 2
                   '03',        # 3
                   'HI TEMP',   # 4
                   '05',        # 5
                   'PWRIN HI',  # 6
                   '07',        # 7
                   '60V HIGH',  # 8
                   'REFL HI',   # 9
                   '10',        # 10
                   'PA DISS',   # 11
                   'POUT HI',   # 12
                   '60V FAIL',  # 13
                   '270V ERR',  # 14
                   'GAIN ERR',  # 15
                   )

    initial_queries = (b';',  # attention!
                       b'^RVM;',  # get version
                       b'^SN;',  # Serial Number
                       b'^ON;',  # on/off status
                       b'^FC;')  # minimum fan speed.

    normal_queries = (b'^FL;',  # faults
                      b'^WS;',  # watts/swr
                      b'^VI;',  # volts/amps
                      b'^OS;',  # standby/operate
                      b'^TM;',  # temperature
                      b'^BN;',  # band
                      b'^SP;',  # speaker
                      )

    def __init__(self):
        self.kpa500_data = ['0'] * 19
        self.kpa500_command_queue = []

        self.kpa500_data[1] = '1'
        self.kpa500_data[8] = '160m,80m,60m,40m,30m,20m,17m,15m,12m,10m,6m'
        self.kpa500_data[9] = '000'
        self.kpa500_data[10] = '000'
        self.kpa500_data[11] = '000'
        self.kpa500_data[13] = '00'
        self.kpa500_data[14] = '0,6,0'
        self.kpa500_data[15] = '0,10,0'
        self.kpa500_data[18] = '4'

        self.network_clients = []

    def band_label_to_number(self, label):
        for i in range(len(self.band_number_to_name)):
            if label == self.band_number_to_name[i]:
                return i
        return None

    def enqueue_command(self, command):
        if isinstance(command, bytes):
            self.kpa500_command_queue.append(command)
        elif isinstance(command, tuple):
            self.kpa500_command_queue.extend(command)
        else:
            print(f'enqueue command received command of type {type(command)} which was not processed.')

    def dequeue_command(self):
        if len(self.kpa500_command_queue) == 0:
            return None
        else:
            return self.kpa500_command_queue.pop(0)

    def get_fault_text(self, fault_code):
        if fault_code.isdigit():
            fault_num = int(fault_code)
            if fault_num < len(self.fault_texts):
                return self.fault_texts[fault_num]
        return fault_code

    def set_amp_off_data(self):
        # reset all the indicators when the amp is turned off.
        self.update_kpa500_data(0, '0')  # OPER button
        self.update_kpa500_data(1, '1')  # STBY button
        self.update_kpa500_data(4, '0')  # POWER button
        self.update_kpa500_data(9, '000')  # CURRENT meter
        self.update_kpa500_data(10, '000')  # POWER meter
        self.update_kpa500_data(11, '000')  # SWR meter
        self.update_kpa500_data(12, '0')  # TEMPERATURE meter
        self.update_kpa500_data(13, '00')  # VOLTAGE meter
        self.update_kpa500_data(17, '0')  # Fan Minimum speed slider

    def update_kpa500_data(self, index, value):
        if self.kpa500_data[index] != value:
            self.kpa500_data[index] = value
            for network_client in self.network_clients:
                if index not in network_client.update_list:
                    network_client.update_list.append(index)
    
