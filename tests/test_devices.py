from datetime import datetime, timezone
from pathlib import Path

from tang_monitor.devices import DeviceRecord, DeviceStore

T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_put_get_forget_persist(tmp_path: Path):
    p = tmp_path / "devices.json"
    s = DeviceStore(p)
    s.put(DeviceRecord("a", "10.0.0.1", T, "flagged"))
    s.put(DeviceRecord("b", "10.0.0.2", T))
    s2 = DeviceStore(p)
    assert s2.get("a") == DeviceRecord("a", "10.0.0.1", T, "flagged")
    assert s2.get("b").flag == "none"
    assert s2.get("zzz") is None
    assert s2.forget("a") is True
    assert s2.forget("a") is False
    s3 = DeviceStore(p)
    assert s3.get("a") is None
    assert [r.device for r in s3.all()] == ["b"]


def test_no_trimming(tmp_path: Path):
    p = tmp_path / "devices.json"
    s = DeviceStore(p)
    for i in range(2000):
        s.put(DeviceRecord(f"d{i}", "10.0.0.1", T))
    assert len(DeviceStore(p).all()) == 2000


def test_corrupt_devices_file_starts_empty(tmp_path: Path):
    p = tmp_path / "devices.json"
    p.write_text("garbage")
    s = DeviceStore(p)
    assert s.all() == []
    assert (tmp_path / "devices.json.corrupt").exists()


import pytest


@pytest.mark.parametrize("content", ["{}", '[{"x": 1}]', "[1]", '"s"'])
def test_wrong_shape_is_quarantined(tmp_path: Path, content):
    p = tmp_path / "devices.json"
    p.write_text(content)
    s = DeviceStore(p)
    assert s.all() == []
    assert (tmp_path / "devices.json.corrupt").read_text() == content
    s.put(DeviceRecord("a", "1.1.1.1", T))
    assert (tmp_path / "devices.json.corrupt").read_text() == content


def test_port_round_trips_and_old_files_load_without_it(tmp_path):
    from tang_monitor.devices import DeviceRecord, DeviceStore
    from datetime import datetime, timezone
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = DeviceStore(tmp_path / "d.json")
    s.put(DeviceRecord("a", "192.168.1.87", at, "none", 7600))
    assert DeviceStore(tmp_path / "d.json").get("a").last_ok_port == 7600
    old = tmp_path / "old.json"
    old.write_text('[{"device": "b", "last_ok_address": "192.168.1.87", "last_ok_at": "2026-01-01T00:00:00+00:00"}]')
    assert DeviceStore(old).get("b").last_ok_port is None
    bad = tmp_path / "bad.json"
    bad.write_text('[{"device": "c", "last_ok_address": "192.168.1.87", "last_ok_at": "2026-01-01T00:00:00+00:00",'
                   ' "last_ok_port": "7600"}]')
    assert DeviceStore(bad).get("c").last_ok_port is None
