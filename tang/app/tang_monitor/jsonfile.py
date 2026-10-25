"""Atomic JSON persistence helpers."""
import json
import os
import tempfile
from pathlib import Path


def load(path: Path, default):
    """Return parsed JSON, or `default` if missing. A corrupt file is moved to `<name>.corrupt`."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return default
    try:
        return json.loads(text)
    except ValueError:
        os.replace(path, path.with_name(path.name + ".corrupt"))
        return default


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
