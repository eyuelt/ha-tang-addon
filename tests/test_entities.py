from datetime import datetime, timedelta, timezone

from tang_monitor.address_check import success_address
from tang_monitor.devices import DeviceRecord
from tang_monitor.entities import build_entities, device_slug, event_data
from tang_monitor.records import LoggedRequest, TangRequest

T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def entry(mins=0, kind="rec", status=200, known=True, host="192.168.1.87:7654", device="mini", ip="10.0.0.5"):
    return LoggedRequest(TangRequest(T + timedelta(minutes=mins), ip, host, kind, status), device, known)


def test_slug():
    assert device_slug("server.lan") == "server_lan"
    assert device_slug("--A  B--") == "a_b"


def test_last_unlock_ignores_adv_and_failed_rec():
    log = [entry(5, kind="adv"), entry(4, status=500), entry(3), entry(1)]
    ents = build_entities(log, [], None, True)
    st, attrs = ents["sensor.tang_last_unlock"]
    assert st == (T + timedelta(minutes=3)).isoformat()
    assert attrs["device"] == "mini" and attrs["ip"] == "10.0.0.5"
    assert attrs["device_class"] == "timestamp"
    assert build_entities([entry(kind="adv")], [], None, True)["sensor.tang_last_unlock"][0] == "unknown"


def test_last_unknown_request():
    log = [entry(1, known=False, ip="9.9.9.9", kind="other"), entry(5), entry(0, known=False)]
    st, attrs = build_entities(log, [], None, False)["sensor.tang_last_unknown_request"]
    assert st == (T + timedelta(minutes=1)).isoformat()
    assert attrs["ip"] == "9.9.9.9" and attrs["kind"] == "other"
    assert attrs["device_class"] == "timestamp"
    assert build_entities([entry()], [], None, False)["sensor.tang_last_unknown_request"][0] == "unknown"


def test_running_and_friendly_names():
    ents = build_entities([], [], None, True)
    assert ents["binary_sensor.tang_running"][0] == "on"
    assert build_entities([], [], None, False)["binary_sensor.tang_running"][0] == "off"
    assert ents["binary_sensor.tang_running"][1]["friendly_name"] == "Tang running"
    assert ents["sensor.tang_last_unlock"][1]["friendly_name"] == "Tang last unlock"
    assert ents["sensor.tang_last_unknown_request"][1]["friendly_name"] == "Tang last unknown request"


def test_address_ok_unavailable_when_pi_unknown():
    d = DeviceRecord("mini", "1.1.1.1", T)
    assert build_entities([], [d], None, True)["binary_sensor.tang_mini_address_ok"][0] == "unavailable"


def test_entity_per_device():
    ds = [DeviceRecord("server", "1.1.1.1", T), DeviceRecord("b", "2.2.2.2", T, "flagged")]
    ents = build_entities([], ds, {"2.2.2.2", "1.1.1.1"}, True)
    st, a = ents["binary_sensor.tang_server_address_ok"]
    assert st == "on"
    assert a == {"friendly_name": "Tang server address OK", "device": "server",
                 "last_address": "1.1.1.1", "pi_addresses": ["1.1.1.1", "2.2.2.2"], "flag": "none"}
    assert ents["binary_sensor.tang_b_address_ok"][0] == "off"
    assert ents["binary_sensor.tang_b_address_ok"][1]["flag"] == "flagged"


def test_event_data_keys():
    d = event_data(entry(known=False, status=404))
    assert d == {"device": "mini", "known": False, "ip": "10.0.0.5", "kind": "rec",
                 "status": 404, "host": "192.168.1.87:7654"}


def test_missing_host_never_becomes_address():
    assert success_address(entry(host=None)) is None
    assert success_address(entry(host="")) is None
    assert success_address(entry()) == "192.168.1.87"
    assert success_address(entry(host="[fd00::5]:7654")) == "fd00::5"
    assert success_address(entry(status=500)) is None
    assert success_address(entry(known=False)) is None
    assert success_address(entry(kind="other")) is None
    assert success_address(entry(kind="adv")) == "192.168.1.87"
