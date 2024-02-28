
import socket
import paho.mqtt.client as mqtt
import json


HOST="0.0.0.0"
PORT=7700

belle_device_id = "belletracker"
trackername="Belle Tracker"

test_cases=[
    # GPS available, LBS OFF
    "#862255061947757#MT710#0000#AUTO#1\r\n#3815$GPRMC,123318.00,A,2238.8946,N,11402.0635,E,,,100124,,,A*5C\r\n##",
    # GPS available, LBS ON
    "#862255061947757#MT710#0000#AUTO#1\r\n#38#$GPRMC,123548.00,A,2238.8936,N,11402.0640,E,,,100124,,,A*5A\r\n##",

    
    # GPS unavailable, LBS ON
    "#862255061947757#MT710#0000#AUTO#1\r\n#3815#460,00,1D29,156153D$GPRMC,121831.00,V,,,,,,,100124,,,A*7C\r\n##",

    # Wifi
    "#862255061986441#MT710#0000#FULL#1\r\n#4200$WIFI,162454.00,A,-69,B0F208DFF4FE,-89,D87D7FF5FDB0,-90,DA7D7FF5FFB1,-91,8072151B8072,,,270224*2C\r\n##"

]

def convert_latitude(lat_ddmm_mmmm):
    # Extract degrees and minutes from the input string
    degrees = int(lat_ddmm_mmmm[:2])
    minutes = float(lat_ddmm_mmmm[2:])

    # Convert minutes to decimal degrees
    decimal_degrees = degrees + (minutes / 60)

    return decimal_degrees

def convert_longitude(longitude_ddmm_mmmm):
    # Extract degrees and minutes from the input string
    degrees = int(longitude_ddmm_mmmm[:3])
    minutes = float(longitude_ddmm_mmmm[3:])

    # Convert minutes to decimal degrees
    decimal_degrees = degrees + (minutes / 60)

    return decimal_degrees


def parse_line(data_string):

    #print(f"Processing Line {data_string}")


    # https://www.mictrack.com/downloads/protocols/Mictrack_Communication_Protocol_For_MT710_V1.0.pdf

    # the string is of the form:
    # #862255061986441#MT710#0000#AUTO#1\r\n#4198$GPRMC,134020.00,A,5040.6934,N,00213.9920,W,,,270224,,,A*42\r\n##\r\n
    # parse the data...
    lines=data_string.splitlines()

    # parse the header
    header=lines[0].split("#")

    if len(header) < 6:
        raise Exception("Header is not of length 5")

    IMEI=header[1]
    GPRSUserName=header[2]
    GPRSPassword=header[3]
    ReportEventStatus=header[4]
    ReportIntervalTime=header[5]

    # now do the body
    body=lines[1]

    # ok, check that we have a seperator
    if body[0] != "#":
        # no, so error, throw exception
        raise Exception("No seperator found")
    
    body=body[1:]
    lbs=False
    batteryVoltage=None

    pre_gprmc=None
    post_gprmc=None
    post_wifi=None
    result=None

    #print(body)
    # if its a wifi
    if "$WIFI" in body:
        pre_gprmc=body.split("$WIFI")[0]
        post_wifi=body.split("$WIFI")[1]

        print(f"Processing Wifi: {post_wifi}")
        
    # see if this is a GPRMC command
    # if $GPRMC is in the body
    if "$GPRMC" in body:

        pre_gprmc=body.split("$GPRMC")[0]
        post_gprmc=body.split("$GPRMC")[1]
        print(f"Processing GPRMC: {post_gprmc}")

    # ok, we need to look for the first # or $
    # Backup Voltage - 38 means 3.8V, 3815 means 3.815V
    pre_gprmc= pre_gprmc.split("#")

    # if the battery voltage ends with a #, then LBS is ON
    if len(pre_gprmc)==2:
        lbs=True

    batteryVoltage=pre_gprmc[0]    

    # if battery voltage is 4 chars, then device by 1000
    if len(batteryVoltage) == 4:
        batteryVoltage=float(batteryVoltage)/1000
    # else devide by 100
    else:
        batteryVoltage=float(batteryVoltage)/10

    #print("batteryVoltage " +str(batteryVoltage))

    cellInfo=None
    # If LBS is OFF, the cell info will be deleted.
    if lbs==True:
        # MCC,MNC,LAC/TAC,Cell ID        
        # 1. If LBS is ON and AGPS is OFF:
        #    - If GPS is available, the cell info will be deleted.
        #    - If GPS is unavailable, the cell info will be shown.
        # Cell Info - 
        #print(body)
        cellInfo = pre_gprmc[1]
        #print("cellInfo " +str(cellInfo))

    if post_gprmc:
        #print(post_gprmc)

        GPRMC=post_gprmc.split(",")

        #print("GPRMC="+str(GPRMC))
        # GPRMC,134020.00,A,5040.6934,N,00213.9920,W,,,270224,,,A*42
        # UTC time - hhmmss.ss
        utcTime=GPRMC[1]

        # Status - A=valid,V=invalid,L=last known position
        status=GPRMC[2]

        # Latitude - ddmm.mmmm
        latitude=GPRMC[3]
        #print("latitude="+str(latitude) )
        if len(latitude)>0:
            # convert the latitude to lat
            latitude=convert_latitude(latitude)

        # N/S Indicator - N=north or S=south
        NS=GPRMC[4]
        if NS=="S":
            latitude=latitude*-1

        # Longitude - Dddmm.mmmm
        longitude=GPRMC[5]
        if len(longitude)>0:
            longitude=convert_longitude(longitude)

        # E/W Indicator - E=east or W=west
        EW=GPRMC[6]

        if EW=="W":
            longitude=longitude*-1

        # Speed Over Ground - knots
        speed=GPRMC[7]

        # Course Over Ground - degrees
        course=GPRMC[8]

        # Date - DDMMYY
        date=GPRMC[9]

        # now combine the time in hhmmss.ss and the date in DDMMYY into a python time
        completetime = date+utcTime


        result={
            "IMEI": IMEI,
            "GPRSUserName": GPRSUserName,
            "GPRSPassword": GPRSPassword,
            "ReportEventStatus": ReportEventStatus,
            "ReportIntervalTime": ReportIntervalTime,
            "batteryVoltage": batteryVoltage,
            "cellInfo": cellInfo,
            "lbs": lbs,
            "status": status,
            "latitude": latitude,
            "NS": NS,
            "longitude": longitude,
            "EW": EW,
            "speed": speed,
            "course": course,
            "timestamp": completetime,
        }

    return(result)

#for test in test_cases:
#    print(parse_line(test))

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

client.connect("retallack.org.uk", 1883, 60)

client.loop_start()

auto_discovery_payload = {
            "json_attributes_topic": belle_device_id+"/attributes",
            "name": trackername
        }

client.publish("homeassistant/device_tracker/"+belle_device_id+"/config", json.dumps(auto_discovery_payload))


with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:

    # allow socket reuse
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # bind to the correct port etc...
    s.bind((HOST, PORT))
    #s.listen()
    
    while True:
        print("Waiting for incomming message")
        # wait for incomming connection
        #conn, addr = s.accept()
        bytesAddressPair=s.recvfrom(0x1000)

        message = bytesAddressPair[0]
        address = bytesAddressPair[1]

        try:
            print(f"New message from: {address}")

            print(message)
            
            # convert the data to string
            data_string = message.decode()
            #print(data_string)

            # need to parse it
            res=parse_line(data_string)

            if res is not None:

                print("got "+str(res))

                payload={
                        "latitude": res["latitude"], 
                        "longitude": res["longitude"], 
                        "gps_accuracy": 1.2
                    }

                print("Sending location update...")

                # publish the location
                client.publish(belle_device_id+"/attributes", json.dumps(payload))
                
                # and also publish the state
                client.publish(belle_device_id+"/imei", res["IMEI"])
                client.publish(belle_device_id+"/reportEventStatus", res["ReportEventStatus"])
                client.publish(belle_device_id+"/reportIntervalTime", res["ReportIntervalTime"])
                client.publish(belle_device_id+"/batteryVoltage", res["batteryVoltage"])

                #datetime_object = datetime.strptime(res["timestamp", '%m/%d/%y %H:%M:%S')

                client.publish(belle_device_id+"/speed", res["speed"])
                client.publish(belle_device_id+"/course", res["course"])
                client.publish(belle_device_id+"/timestamp", res["timestamp"])


        except Exception as e:
            print(e)

            

