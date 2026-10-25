from tang_monitor.keys import jwk_thumbprint, load_keys, ensure_keys
import json
import sys

RFC7638_RSA = {"kty": "RSA", "e": "AQAB", "n": "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSoc_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw"}

def test_rfc7638_vector():
    assert jwk_thumbprint(RFC7638_RSA, "sha256") == "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"

def test_ec_uses_only_required_members():
    a = {"kty": "EC", "crv": "P-521", "x": "AX", "y": "AY", "alg": "ES512", "key_ops": ["verify"]}
    b = {"kty": "EC", "crv": "P-521", "x": "AX", "y": "AY"}
    assert jwk_thumbprint(a, "sha256") == jwk_thumbprint(b, "sha256")
    assert jwk_thumbprint(a, "sha1") != jwk_thumbprint(a, "sha256")

def test_load_keys_classifies_and_skips_hidden(tmp_path):
    (tmp_path / "sig.jwk").write_text(json.dumps({"kty": "EC", "crv": "P-521", "x": "S", "y": "S", "key_ops": ["sign", "verify"], "alg": "ES512"}))
    (tmp_path / "exc.jwk").write_text(json.dumps({"kty": "EC", "crv": "P-521", "x": "E", "y": "E", "key_ops": ["deriveKey"], "alg": "ECMR"}))
    (tmp_path / ".old.jwk").write_text("{}")
    keys = {k.file_stem: k for k in load_keys(tmp_path)}
    assert set(keys) == {"sig", "exc"}
    assert keys["sig"].use == "signing" and keys["exc"].use == "exchange"

def _fake_keygen(tmp_path):
    script = tmp_path / "keygen.py"
    script.write_text("import sys, pathlib\npathlib.Path(sys.argv[1], 'k.jwk').write_text('{}')\n")
    return (sys.executable, str(script))

def test_ensure_keys_runs_keygen_when_empty(tmp_path):
    keydir = tmp_path / "keys"
    keydir.mkdir()
    (keydir / ".hidden.jwk").write_text("{}")
    ensure_keys(keydir, _fake_keygen(tmp_path))
    assert (keydir / "k.jwk").exists()

def test_ensure_keys_skips_when_keys_exist(tmp_path):
    keydir = tmp_path / "keys"
    keydir.mkdir()
    (keydir / "a.jwk").write_text("{}")
    ensure_keys(keydir, _fake_keygen(tmp_path))
    assert not (keydir / "k.jwk").exists()
