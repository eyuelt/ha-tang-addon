"""Tang key loading and RFC 7638 JWK thumbprints."""
import base64
import hashlib
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_REQUIRED = {
    "EC": ("crv", "kty", "x", "y"),
    "RSA": ("e", "kty", "n"),
    "oct": ("k", "kty"),
}


@dataclass(frozen=True)
class KeyInfo:
    file_stem: str
    use: Literal["signing", "exchange"]
    s256: str
    s1: str


def jwk_thumbprint(jwk: dict, alg: Literal["sha256", "sha1"]) -> str:
    members = _REQUIRED[jwk["kty"]]
    canonical = json.dumps({m: jwk[m] for m in members}, separators=(",", ":"), sort_keys=True)
    digest = hashlib.new(alg, canonical.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _keyfiles(keydir: Path) -> list[Path]:
    return sorted(p for p in keydir.glob("*.jwk") if not p.name.startswith("."))


def load_keys(keydir: Path) -> list[KeyInfo]:
    keys = []
    for path in _keyfiles(keydir):
        jwk = json.loads(path.read_text())
        ops = jwk.get("key_ops", [])
        use = "signing" if "sign" in ops or "verify" in ops else "exchange"
        keys.append(KeyInfo(path.stem, use, jwk_thumbprint(jwk, "sha256"), jwk_thumbprint(jwk, "sha1")))
    return keys


def ensure_keys(keydir: Path, keygen: Sequence[str] = ("/usr/libexec/tangd-keygen",)) -> None:
    if not _keyfiles(keydir):
        subprocess.run([*keygen, str(keydir)], check=True)
