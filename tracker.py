import socket
import paho.mqtt.client as mqtt
import json
import geopy.distance
from datetime import datetime

HOST = "0.0.0.0"
PORT = 7700

belle_device_id = "belletracker"
trackername = "Belle Tracker"

# MQTT broker
MQTT_HOST = "retallack.org.uk"
MQTT_PORT = 1883

# Home Assistant discovery prefix (default)
HA_PREFIX = "homeassistant"

# Report Event Status values observed in real traffic (see docs/notes).
# Charging-related states drive the "charging" binary sensor.
CHARGING_EVENTS = {"PLUG", "FULL"}      # device is on the charger
NOT_CHARGING_EVENTS = {"UNPLUG"}        # charger disconnected
# Movement/mode states we have actually seen: TOWED, HT, AUTO.

# Sample messages captured from the device, used by the test suite and for
# manual sanity checks. These are REAL observed payloads, not spec examples.
test_cases = [
    # GPS available (observed)
    "#862255061986441#MT710#0000#TOWED#1\r\n#3897$GPRMC,120953.00,A,5040.6991,N,00213.5055,W,0.70,5.50,211026,,,A*42\r\n##",
    # WiFi, single AP (observed)
    "#862255061986441#MT710#0000#HT#1\r\n#4038$WIFI,183626.00,A,-52,B0F208DFF4FE,,,,,,,,,191026*00\r\n##",
    # WiFi, two APs (observed)
    "#862255061986441#MT710#0000#TOWED#1\r\n#4051$WIFI,064551.00,A,-51,B0F208DFF4FE,-94,6CA0B4BDF3AA,,,,,,,201026*23\r\n##",
    # WiFi with empty time AND empty date (observed Oct 20 13:20)
    "#862255061986441#MT710#0000#HT#1\r\n#3997$WIFI,,A,-54,B0F208DFF4FE,,,,,,,,,*2D\r\n##",
    # Charger connected (observed)
    "#862255061986441#MT710#0000#PLUG#1\r\n#3756$WIFI,234102.00,A,-27,B0F208DFF4FE,,,,,,,,,021026*06",
    # Charger disconnected (observed)
    "#862255061986441#MT710#0000#UNPLUG#1\r\n#3756$WIFI,234111.00,A,-25,B0F208DFF4FE,-92,8072151B8072,,,,,,,021026*2C",
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


def parse_battery_voltage(raw):
    """Backup voltage. Observed form is always 4 digits, e.g. 3897 -> 3.897V."""
    if len(raw) == 4:
        return float(raw) / 1000
    # Fallback for shorter forms (e.g. 38 -> 3.8V)
    return float(raw) / 10


def parse_wifi(post_wifi):
    """Parse a $WIFI body.

    Observed layouts (note trailing commas padding to a fixed width, and that
    both the UTC time and trailing date can be empty):

        ,183626.00,A,-52,B0F208DFF4FE,,,,,,,,,191026
        ,064551.00,A,-51,B0F208DFF4FE,-94,6CA0B4BDF3AA,,,,,,,201026
        ,,A,-54,B0F208DFF4FE,,,,,,,,,            (empty time and date)

    Returns (status, utcTime, date, access_points) where access_points is a
    list of {"rssi": int, "mac": str} ordered as received (strongest first).
    """
    fields = post_wifi.split(",")
    # strip checksum off the final token if present (e.g. "191026*00")
    if fields and "*" in fields[-1]:
        fields[-1] = fields[-1].split("*")[0]

    # field 0 is the empty token before the first comma
    utcTime = fields[1] if len(fields) > 1 else ""
    status = fields[2] if len(fields) > 2 else ""

    access_points = []
    # RSSI/MAC pairs start at index 3 and run until the trailing date field.
    i = 3
    while i + 1 < len(fields):
        rssi = fields[i].strip()
        mac = fields[i + 1].strip()
        # A valid pair is a numeric RSSI followed by a MAC-looking token.
        if rssi and mac and (rssi.lstrip("-").isdigit()) and len(mac) == 12:
            access_points.append({"rssi": int(rssi), "mac": mac})
            i += 2
        else:
            i += 1

    # The date (DDMMYY) is the last non-empty numeric token that is not a pair.
    date = ""
    last = fields[-1].strip() if fields else ""
    if last.isdigit() and len(last) == 6:
        date = last

    return status, utcTime, date, access_points


def classify_charging(report_event_status):
    """Map an observed Report Event Status to a charging state.

    Returns True (charging), False (not charging), or None (event tells us
    nothing about charging, e.g. TOWED / HT / AUTO).
    """
    if report_event_status in CHARGING_EVENTS:
        return True
    if report_event_status in NOT_CHARGING_EVENTS:
        return False
    return None


def parse_line(data_string):
    """Parse an MT710 report (GPS or WiFi) into a dict, or None if unparseable.

    https://www.mictrack.com/downloads/protocols/Mictrack_Communication_Protocol_For_MT710_V1.0.pdf

    Example header + body:
    #862255061986441#MT710#0000#AUTO#1\r\n#4198$GPRMC,134020.00,A,...*42\r\n##\r\n
    """
    lines = data_string.splitlines()

    # parse the header
    header = lines[0].split("#")

    if len(header) < 6:
        raise Exception("Header is not of length 5")

    IMEI = header[1]
    GPRSUserName = header[2]
    GPRSPassword = header[3]
    ReportEventStatus = header[4]
    ReportIntervalTime = header[5]

    # now do the body
    body = lines[1]

    # ok, check that we have a seperator
    if body[0] != "#":
        raise Exception("No seperator found")

    body = body[1:]
    lbs = False

    pre_gprmc = None
    post_gprmc = None
    post_wifi = None
    result = None

    report_type = None

    # WiFi report?
    if "$WIFI" in body:
        report_type = "wifi"
        pre_gprmc = body.split("$WIFI")[0]
        post_wifi = body.split("$WIFI")[1]

    # GPS (GPRMC) report?
    if "$GPRMC" in body:
        report_type = "gps"
        pre_gprmc = body.split("$GPRMC")[0]
        post_gprmc = body.split("$GPRMC")[1]

    if pre_gprmc is None:
        # Neither GPS nor WiFi body recognised.
        return None

    # Backup Voltage - 38 means 3.8V, 3815 means 3.815V. If LBS is ON the
    # voltage is followed by a "#" (and then cell info).
    pre_gprmc = pre_gprmc.split("#")
    if len(pre_gprmc) == 2:
        lbs = True

    batteryVoltage = parse_battery_voltage(pre_gprmc[0])

    cellInfo = None
    if lbs:
        # MCC,MNC,LAC/TAC,Cell ID
        cellInfo = pre_gprmc[1]

    charging = classify_charging(ReportEventStatus)

    # Common fields present on every report type.
    result = {
        "IMEI": IMEI,
        "GPRSUserName": GPRSUserName,
        "GPRSPassword": GPRSPassword,
        "ReportEventStatus": ReportEventStatus,
        "ReportIntervalTime": ReportIntervalTime,
        "report_type": report_type,
        "batteryVoltage": batteryVoltage,
        "cellInfo": cellInfo,
        "lbs": lbs,
        "charging": charging,
    }

    if post_gprmc is not None:
        # GPRMC,134020.00,A,5040.6934,N,00213.9920,W,,,270224,,,A*42
        GPRMC = post_gprmc.split(",")

        utcTime = GPRMC[1]
        status = GPRMC[2]  # A=valid, V=invalid, L=last known position

        latitude = GPRMC[3]
        if len(latitude) > 0:
            latitude = convert_latitude(latitude)

        NS = GPRMC[4]
        if NS == "S" and latitude != "":
            latitude = latitude * -1

        longitude = GPRMC[5]
        if len(longitude) > 0:
            longitude = convert_longitude(longitude)

        EW = GPRMC[6]
        if EW == "W" and longitude != "":
            longitude = longitude * -1

        speed = GPRMC[7]
        course = GPRMC[8]
        date = GPRMC[9]

        # combine DDMMYY + hhmmss.ss (device-reported time, authoritative)
        completetime = date + utcTime

        result.update({
            "status": status,
            "latitude": latitude,
            "NS": NS,
            "longitude": longitude,
            "EW": EW,
            "speed": speed,
            "course": course,
            "timestamp": completetime,
        })

    elif post_wifi is not None:
        status, utcTime, date, access_points = parse_wifi(post_wifi)
        completetime = date + utcTime

        # strongest AP is the first one received
        strongest_rssi = access_points[0]["rssi"] if access_points else None

        result.update({
            "status": status,
            # WiFi reports carry no fix; do NOT fabricate lat/lon.
            "latitude": None,
            "longitude": None,
            "access_points": access_points,
            "mac_list": [ap["mac"] for ap in access_points],
            "rssi": strongest_rssi,
            "timestamp": completetime,
        })

    return result


# ---------------------------------------------------------------------------
# Home Assistant MQTT Discovery
# https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery
# ---------------------------------------------------------------------------

def _device_block(imei):
    """Shared device block so all entities group under one HA device."""
    return {
        "identifiers": [belle_device_id],
        "name": trackername,
        "manufacturer": "Mictrack",
        "model": "MT710",
        "serial_number": imei,
    }


def build_discovery_configs(imei):
    """Return a list of (discovery_topic, config_payload) tuples.

    One shared device block ties every entity to the same HA device. Every
    entity gets a stable unique_id. Only data we actually receive is exposed.
    """
    dev = _device_block(imei)
    base = belle_device_id
    configs = []

    # device_tracker (position via JSON attributes)
    configs.append((
        f"{HA_PREFIX}/device_tracker/{base}/config",
        {
            "name": None,  # use the device name
            "unique_id": f"{base}_tracker",
            "json_attributes_topic": f"{base}/attributes",
            "device": dev,
        },
    ))

    # charging binary sensor (PLUG/UNPLUG/FULL)
    configs.append((
        f"{HA_PREFIX}/binary_sensor/{base}_charging/config",
        {
            "name": "Charging",
            "unique_id": f"{base}_charging",
            "state_topic": f"{base}/charging",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "battery_charging",
            "device": dev,
        },
    ))

    # battery percentage
    configs.append((
        f"{HA_PREFIX}/sensor/{base}_battery/config",
        {
            "name": "Battery",
            "unique_id": f"{base}_battery",
            "state_topic": f"{base}/batteryPercent",
            "device_class": "battery",
            "unit_of_measurement": "%",
            "state_class": "measurement",
            "device": dev,
        },
    ))

    # battery voltage
    configs.append((
        f"{HA_PREFIX}/sensor/{base}_voltage/config",
        {
            "name": "Battery voltage",
            "unique_id": f"{base}_voltage",
            "state_topic": f"{base}/batteryVoltage",
            "device_class": "voltage",
            "unit_of_measurement": "V",
            "state_class": "measurement",
            "device": dev,
        },
    ))

    # speed (mph)
    configs.append((
        f"{HA_PREFIX}/sensor/{base}_speed/config",
        {
            "name": "Speed",
            "unique_id": f"{base}_speed",
            "state_topic": f"{base}/speedmph",
            "device_class": "speed",
            "unit_of_measurement": "mph",
            "state_class": "measurement",
            "device": dev,
        },
    ))

    # course / heading
    configs.append((
        f"{HA_PREFIX}/sensor/{base}_course/config",
        {
            "name": "Course",
            "unique_id": f"{base}_course",
            "state_topic": f"{base}/course",
            "unit_of_measurement": "°",
            "state_class": "measurement",
            "device": dev,
        },
    ))

    # report event status (TOWED / HT / AUTO / PLUG / UNPLUG ...)
    configs.append((
        f"{HA_PREFIX}/sensor/{base}_event/config",
        {
            "name": "Report event",
            "unique_id": f"{base}_event",
            "state_topic": f"{base}/reportEventStatus",
            "icon": "mdi:information-outline",
            "device": dev,
        },
    ))

    # strongest WiFi RSSI
    configs.append((
        f"{HA_PREFIX}/sensor/{base}_rssi/config",
        {
            "name": "WiFi RSSI",
            "unique_id": f"{base}_rssi",
            "state_topic": f"{base}/rssi",
            "device_class": "signal_strength",
            "unit_of_measurement": "dBm",
            "state_class": "measurement",
            "device": dev,
        },
    ))

    return configs


def publish_discovery(client, imei):
    for topic, payload in build_discovery_configs(imei):
        client.publish(topic, json.dumps(payload), retain=True)


def main():
    print("Starting Tracker")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    discovery_sent = False
    last_pos = None
    last_pos_time = None

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))

        while True:
            print("Waiting for incomming message")
            bytesAddressPair = s.recvfrom(0x1000)
            message = bytesAddressPair[0]
            address = bytesAddressPair[1]

            try:
                print(f"New message from: {address}")
                print(message)

                data_string = message.decode()
                res = parse_line(data_string)

                if res is None:
                    continue

                print("got " + str(res))

                # publish HA discovery once we know the IMEI
                if not discovery_sent:
                    publish_discovery(client, res["IMEI"])
                    discovery_sent = True

                # Always-available telemetry (present on GPS and WiFi reports)
                client.publish(belle_device_id + "/imei", res["IMEI"])
                client.publish(belle_device_id + "/reportEventStatus", res["ReportEventStatus"])
                client.publish(belle_device_id + "/reportIntervalTime", res["ReportIntervalTime"])
                client.publish(belle_device_id + "/reportType", res["report_type"])
                client.publish(belle_device_id + "/batteryVoltage", res["batteryVoltage"])

                # charging binary sensor (only publish when the event tells us)
                if res["charging"] is True:
                    client.publish(belle_device_id + "/charging", "ON")
                elif res["charging"] is False:
                    client.publish(belle_device_id + "/charging", "OFF")

                # battery percent (3.59V = 0%, 4.19V = 100%)
                lower_limit = 3.59
                upper_limit = 4.19
                battery_percent = float(res["batteryVoltage"]) - lower_limit
                if battery_percent < 0:
                    battery_percent = 0
                battery_percent = (battery_percent / (upper_limit - lower_limit)) * 100
                if battery_percent > 100:
                    battery_percent = 100
                client.publish(belle_device_id + "/batteryPercent", int(battery_percent))

                client.publish(belle_device_id + "/timestamp", res["timestamp"])

                if res["report_type"] == "gps" and res.get("status") == "A":
                    current_pos = (res["latitude"], res["longitude"])

                    payload = {
                        "latitude": res["latitude"],
                        "longitude": res["longitude"],
                        "gps_accuracy": 1.2,
                        "source_type": "gps",
                    }
                    print("Sending location update...")

                    speed_mph = 0
                    if len(res["speed"]) > 0:
                        speed_mph = float(res["speed"]) * 1.15078

                    distance = 0
                    if last_pos is not None and ((datetime.now() - last_pos_time).total_seconds() < 600):
                        distance = geopy.distance.geodesic(last_pos, current_pos).km

                    client.publish(belle_device_id + "/attributes", json.dumps(payload))
                    client.publish(belle_device_id + "/speed", res["speed"])
                    client.publish(belle_device_id + "/speedmph", speed_mph)
                    client.publish(belle_device_id + "/course", res["course"])
                    client.publish(belle_device_id + "/distance", distance)

                    last_pos = current_pos
                    last_pos_time = datetime.now()

                elif res["report_type"] == "wifi":
                    # WiFi report: no fix. Expose the AP data, RSSI and status.
                    print("WiFi report (no position)...")
                    if res.get("rssi") is not None:
                        client.publish(belle_device_id + "/rssi", res["rssi"])
                    client.publish(
                        belle_device_id + "/wifi",
                        json.dumps({
                            "status": res.get("status"),
                            "access_points": res.get("access_points", []),
                            "mac_list": res.get("mac_list", []),
                            "rssi": res.get("rssi"),
                        }),
                    )

            except Exception as e:
                print(e)


if __name__ == "__main__":
    main()
