import serial


class TrackerConfig():

    def __init__(self):
        # open the serial port
        # set the baud rate to 921600
        self.ser = serial.Serial('/dev/ttyUSB0', 921600, timeout=1)


    def wait_for_reply(self, required_reply, timeout=2, error=True):

        res=None
        # set the timeout on the serial port
        self.ser.timeout=timeout

        # wait for the correct reply
        running=""
        print(f"Waiting for {required_reply}")
        while True:
            reply=self.ser.read(20)
            if reply==b'':
                break
            running+=reply.decode()

            print(f"Got {running}")
            #print(f'Got {running}')
            if required_reply in running:
                res=running
                break
            pass
    
        # if res is None, and error is True, raise an error
        if res is None and error:
            raise Exception(f"Did not get the required reply {required_reply}")

        return res

    def start(self):
        
        # and wait for the correct reply
        while True:
            # send the start command
            self.ser.write(b'ETS')

            if self.wait_for_reply("ETS,OK", timeout=1, error=False)!=None:
                break

    def reset(self):

        # send the start command
        self.ser.write(b'RESET')

        # and wait for the correct reply
        self.wait_for_reply("RESET,OK")
        

    def set_password(self, password):
        # send the password command
        self.ser.write(f'777,{password}'.encode())

        # and wait for the correct reply
        self.wait_for_reply("777,OK")

    def set_apn(self, apn):
        # send the apn command
        self.ser.write(f'803,{apn},,'.encode())

        # and wait for the correct reply
        self.wait_for_reply("803,OK")
        pass

    def set_mode0(self,t1,t2):
        # send the mode command
        self.ser.write(f'MODE,0,{t1},{t2}'.encode())

        # and wait for the correct reply
        self.wait_for_reply("MODE,OK")

    def set_mode1(self,t1):
        # send the mode command
        self.ser.write(f'MODE,1,{t1}'.encode())

        # and wait for the correct reply
        self.wait_for_reply("MODE,OK")        

    def set_network(self, address, port):
        # send the IP and port command
        self.ser.write(f'804,{address},{port}'.encode())

        # and wait for the correct reply
        self.wait_for_reply("804,OK")

    def set_protocol(self, protocol):
        # send the protocol command
        self.ser.write(f'800,{protocol}'.encode())

        # and wait for the correct reply
        self.wait_for_reply("800,OK")

    def get_config(self):
        self.ser.write(f'RCONF'.encode())

        self.ser.timeout=1
        reply=self.ser.read(2000) 
        print(reply.decode())     

    def save_and_exit(self):
        # QTS
        self.ser.write(b'QTS')
        self.wait_for_reply("QTS,OK")

    def where(self):
        #WHERE
        self.ser.write(b'WHERE')
        self.ser.timeout=20
        reply=self.ser.read(2000) 
        print(reply.decode())   


    def configure(self, active_interval, inactive_interval=20, testmode=False):

        self.start()

        self.reset()

        self.set_password("1924")

        self.set_apn("iot.1nce.net")

        self.set_network("retallack.org.uk",7700)

        self.set_protocol("UDP")

        if testmode:
            self.set_mode1(active_interval)
        else:
            self.set_mode0(active_interval,inactive_interval)

        self.start()

        self.get_config()

        self.save_and_exit()




cfg=TrackerConfig()

#cfg.configure(10, testmode=True)

#cfg.get_position()