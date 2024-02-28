import serial
import yaml


class TrackerConfig():

    def __init__(self, configfile):
        # open the serial port
        # set the baud rate to 921600
        self.ser = serial.Serial('/dev/ttyUSB0', 921600, timeout=1)

        # load in the yaml config file
        self.config=yaml.safe_load(open(configfile))
        


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
        # 1. T1 is between 10-600 seconds, and T2 is between 1-24 hours.
        # 2. When device is vibrate it will run as T1 and when device detect to still it will run as T2
        # send the mode command
        self.ser.write(f'MODE,0,{t1},{t2}'.encode())

        # and wait for the correct reply
        self.wait_for_reply("MODE,OK")

    def set_mode1(self,t1):
        # T is the report interval time, and its range is between 60-600 seconds
        # send the mode command
        self.ser.write(f'MODE,1,{t1}'.encode())

        # and wait for the correct reply
        self.wait_for_reply("MODE,OK")   


    def set_mode7(self,t1, t2):
        # T1 is between 10-1440 minutes, and T2 is between 1-24 hours.
        # When device is vibrate it will run as T1 and when device detect to still it will run as T2.
        # * MODE 7 is an optimized version based on MODE 0, with lower
        # power consumption than MODE 0     
        self.ser.write(f'MODE,7,{t1},{t2}'.encode())

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


    def configure(self):

        self.start()

        self.reset()

        self.set_password(self.config["password"])

        self.set_apn(self.config["apn"])

        self.set_network(self.config["host"],self.config["port"])

        self.set_protocol(self.config["protocol"])

        active_interval=self.config["activeInterval"]
        inactive_interval=self.config["inactiveInterval"]

        if self.config["mode"] == 0:
            self.set_mode0(active_interval,inactive_interval)
        elif self.config["mode"] == 1:
            self.set_mode1(active_interval)
        elif self.config["mode"] == 7:
            self.set_mode7(active_interval, inactive_interval) 
        else:
            print("Unsupported Mode")

        self.start()

        self.get_config()

        self.save_and_exit()




cfg=TrackerConfig("config.yaml")

cfg.configure()

#cfg.get_position()