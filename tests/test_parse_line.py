"""Tests for tracker.parse_line and related helpers.

Every sample here is a REAL payload observed from the MT710 in the logs,
not an example copied from the protocol spec.
"""

import pytest

from tracker import (
    parse_line,
    parse_wifi,
    parse_battery_voltage,
    classify_charging,
    build_discovery_configs,
)


# --- GPS reports -----------------------------------------------------------

def test_gps_valid_fix():
    msg = ("#862255061986441#MT710#0000#TOWED#1\r\n"
           "#3897$GPRMC,120953.00,A,5040.6991,N,00213.5055,W,0.70,5.50,211026,,,A*42\r\n##")
    res = parse_line(msg)

    assert res["report_type"] == "gps"
    assert res["IMEI"] == "862255061986441"
    assert res["ReportEventStatus"] == "TOWED"
    assert res["status"] == "A"
    assert res["batteryVoltage"] == pytest.approx(3.897)
    assert res["latitude"] == pytest.approx(50.6783183, abs=1e-5)
    assert res["longitude"] == pytest.approx(-2.2250916, abs=1e-5)  # W -> negative
    assert res["speed"] == "0.70"
    assert res["course"] == "5.50"
    assert res["timestamp"] == "211026120953.00"  # DDMMYY + hhmmss.ss
    assert res["charging"] is None  # TOWED says nothing about charging


def test_gps_second_sample_longitude_west():
    msg = ("#862255061986441#MT710#0000#TOWED#1\r\n"
           "#3908$GPRMC,121454.00,A,5040.7917,N,00213.6227,W,2.50,260.40,211026,,,A*42\r\n##")
    res = parse_line(msg)
    assert res["longitude"] < 0
    assert res["latitude"] == pytest.approx(50.6798616, abs=1e-5)
    assert res["batteryVoltage"] == pytest.approx(3.908)


# --- WiFi reports ----------------------------------------------------------

def test_wifi_single_ap():
    msg = ("#862255061986441#MT710#0000#HT#1\r\n"
           "#4038$WIFI,183626.00,A,-52,B0F208DFF4FE,,,,,,,,,191026*00\r\n##")
    res = parse_line(msg)

    assert res["report_type"] == "wifi"
    assert res["ReportEventStatus"] == "HT"
    assert res["latitude"] is None      # no fabricated position
    assert res["longitude"] is None
    assert res["rssi"] == -52
    assert res["mac_list"] == ["B0F208DFF4FE"]
    assert res["access_points"] == [{"rssi": -52, "mac": "B0F208DFF4FE"}]
    assert res["timestamp"] == "191026183626.00"
    assert res["batteryVoltage"] == pytest.approx(4.038)


def test_wifi_two_aps_ordered_strongest_first():
    msg = ("#862255061986441#MT710#0000#TOWED#1\r\n"
           "#4051$WIFI,064551.00,A,-51,B0F208DFF4FE,-94,6CA0B4BDF3AA,,,,,,,201026*23\r\n##")
    res = parse_line(msg)

    assert res["mac_list"] == ["B0F208DFF4FE", "6CA0B4BDF3AA"]
    assert res["rssi"] == -51  # strongest (first) AP
    assert res["access_points"][1] == {"rssi": -94, "mac": "6CA0B4BDF3AA"}


def test_wifi_empty_time_and_date():
    """Observed Oct 20 13:20 line: no UTC time and no trailing date."""
    msg = ("#862255061986441#MT710#0000#HT#1\r\n"
           "#3997$WIFI,,A,-54,B0F208DFF4FE,,,,,,,,,*2D\r\n##")
    res = parse_line(msg)

    assert res["report_type"] == "wifi"
    assert res["status"] == "A"
    assert res["rssi"] == -54
    assert res["mac_list"] == ["B0F208DFF4FE"]
    assert res["timestamp"] == ""  # empty date + empty time


# --- Charging events -------------------------------------------------------

def test_plug_event_is_charging():
    msg = ("#862255061986441#MT710#0000#PLUG#1\r\n"
           "#3756$WIFI,234102.00,A,-27,B0F208DFF4FE,,,,,,,,,021026*06")
    res = parse_line(msg)
    assert res["ReportEventStatus"] == "PLUG"
    assert res["charging"] is True
    assert res["rssi"] == -27


def test_unplug_event_is_not_charging():
    msg = ("#862255061986441#MT710#0000#UNPLUG#1\r\n"
           "#3756$WIFI,234111.00,A,-25,B0F208DFF4FE,-92,8072151B8072,,,,,,,021026*2C")
    res = parse_line(msg)
    assert res["ReportEventStatus"] == "UNPLUG"
    assert res["charging"] is False
    assert res["mac_list"] == ["B0F208DFF4FE", "8072151B8072"]


# --- Helpers ---------------------------------------------------------------

def test_parse_battery_voltage():
    assert parse_battery_voltage("3897") == pytest.approx(3.897)
    assert parse_battery_voltage("4200") == pytest.approx(4.200)
    assert parse_battery_voltage("38") == pytest.approx(3.8)


def test_classify_charging():
    assert classify_charging("PLUG") is True
    assert classify_charging("FULL") is True
    assert classify_charging("UNPLUG") is False
    assert classify_charging("TOWED") is None
    assert classify_charging("HT") is None
    assert classify_charging("AUTO") is None


def test_parse_wifi_strips_checksum():
    status, utc, date, aps = parse_wifi(",183626.00,A,-52,B0F208DFF4FE,,,,,,,,,191026*00")
    assert status == "A"
    assert utc == "183626.00"
    assert date == "191026"
    assert aps == [{"rssi": -52, "mac": "B0F208DFF4FE"}]


# --- Discovery -------------------------------------------------------------

def test_discovery_has_shared_device_and_unique_ids():
    configs = build_discovery_configs("862255061986441")
    assert len(configs) >= 8

    unique_ids = set()
    for topic, payload in configs:
        assert payload["device"]["identifiers"] == ["belletracker"]
        assert payload["device"]["serial_number"] == "862255061986441"
        uid = payload["unique_id"]
        assert uid not in unique_ids, f"duplicate unique_id {uid}"
        unique_ids.add(uid)

    topics = [t for t, _ in configs]
    assert any("binary_sensor" in t and "charging" in t for t in topics)
    assert any("device_tracker" in t for t in topics)


def test_charging_binary_sensor_config():
    configs = dict(build_discovery_configs("862255061986441"))
    topic = "homeassistant/binary_sensor/belletracker_charging/config"
    assert topic in configs
    cfg = configs[topic]
    assert cfg["device_class"] == "battery_charging"
    assert cfg["payload_on"] == "ON"
    assert cfg["payload_off"] == "OFF"
