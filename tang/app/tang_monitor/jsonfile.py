"""Atomic JSON persistence helpers."""
import json
import os
import tempfile
from pathlib import Path


def load(path: Path, default):
    """Return parsed JSON, or `default` if missing. A corrupt file is moved to `<name>.corrupt`."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except ValueError:  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        quarantine(path)
        return default


def quarantine(path: Path) -> None:
    """Move a bad file aside to `<name>.corrupt` so it is never overwritten."""
    os.replace(path, path.with_name(path.name + ".corrupt"))


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
