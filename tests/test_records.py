from datetime import datetime, timezone
from pathlib import Path

from tang_monitor.records import LoggedRequest, RequestLog, TangRequest


def _entry(i, host="h"):
    req = TangRequest(at=datetime(2026, 1, 1, tzinfo=timezone.utc), ip=f"10.0.0.{i % 250}",
                      host=host, kind="adv", status=200)
    return LoggedRequest(request=req, device=f"dev{i}", known=True)


def test_log_keeps_newest_500(tmp_path: Path):
    p = tmp_path / "log.json"
    log = RequestLog(p)
    for i in range(505):
        log.append(_entry(i))
    recent = log.recent()
    assert len(recent) == 500
    assert recent[0].device == "dev504"
    assert recent[-1].device == "dev5"
    again = RequestLog(p).recent()
    assert [e.device for e in again] == [e.device for e in recent]


def test_log_roundtrips_datetimes_and_none_host(tmp_path: Path):
    p = tmp_path / "log.json"
    at = datetime(2026, 3, 4, 5, 6, 7, 123456, tzinfo=timezone.utc)
    e = LoggedRequest(TangRequest(at=at, ip="1.2.3.4", host=None, kind="other", status=None), "x", False)
    RequestLog(p).append(e)
    got = RequestLog(p).recent()[0]
    assert got == e
    assert got.request.at.tzinfo is not None


def test_corrupt_log_file_starts_empty_and_is_kept_as_corrupt(tmp_path: Path):
    p = tmp_path / "log.json"
    p.write_text("{not json")
    log = RequestLog(p)
    assert log.recent() == []
    assert (tmp_path / "log.json.corrupt").read_text() == "{not json"
    log.append(_entry(1))
    assert len(RequestLog(p).recent()) == 1
