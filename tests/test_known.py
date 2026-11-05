from tang_monitor.known import KnownDevices


def test_add_remove_ids(tmp_path):
    k = KnownDevices(tmp_path / "known.json")
    assert k.ids() == []
    assert k.add("server.lan") is True
    assert k.add("server.lan") is False
    assert k.add("10.0.0.5") is True
    assert k.ids() == ["server.lan", "10.0.0.5"]
    assert k.remove("server.lan") is True
    assert k.remove("server.lan") is False
    assert k.ids() == ["10.0.0.5"]


def test_matches_name_case_and_trailing_dot(tmp_path):
    k = KnownDevices(tmp_path / "known.json")
    k.add("Server.LAN")
    assert k.matches("server.lan.", "192.168.1.9")
    assert not k.matches("laptop.lan", "192.168.1.9")
    assert not k.matches(None, "192.168.1.9")


def test_matches_ip_canonical(tmp_path):
    k = KnownDevices(tmp_path / "known.json")
    k.add("fe80:0:0:0:0:0:0:1")
    assert k.matches(None, "fe80::1")
    assert not k.matches(None, "fe80::2")
    k.add("10.0.0.7")
    assert k.matches("other.lan", "10.0.0.7")


def test_persists_across_instances(tmp_path):
    p = tmp_path / "known.json"
    k = KnownDevices(p)
    k.add("server.lan")
    k.add("laptop.lan")
    k.remove("laptop.lan")
    assert KnownDevices(p).ids() == ["server.lan"]


def test_corrupt_file_quarantined(tmp_path):
    p = tmp_path / "known.json"
    p.write_text("{not json")
    assert KnownDevices(p).ids() == []
    assert (tmp_path / "known.json.corrupt").exists()


def test_wrong_shape_quarantined(tmp_path):
    for i, bad in enumerate(['{"a": 1}', '[1, 2]']):
        p = tmp_path / f"k{i}.json"
        p.write_text(bad)
        assert KnownDevices(p).ids() == []
        assert (tmp_path / f"k{i}.json.corrupt").exists()
        assert not p.exists()
