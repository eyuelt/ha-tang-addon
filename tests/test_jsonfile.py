from tang_monitor import jsonfile


def test_invalid_utf8_is_quarantined(tmp_path):
    p = tmp_path / "x.json"
    p.write_bytes(b"\xff\xfe\x00bad")
    assert jsonfile.load(p, []) == []
    assert (tmp_path / "x.json.corrupt").read_bytes() == b"\xff\xfe\x00bad"
    assert not p.exists()


def test_missing_returns_default(tmp_path):
    assert jsonfile.load(tmp_path / "nope.json", {"a": 1}) == {"a": 1}
