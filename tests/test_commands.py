import subprocess

import pytest

from tang_monitor import commands
from tang_monitor.commands import (
    device_commands, find_steps, fix_command, one_step_fix_script, tang_config,
)
from tang_monitor.keys import KeyInfo

SIG = KeyInfo("sig", "signing", "SIGS256", "SIGS1")
EX1 = KeyInfo("ex1", "exchange", "EX1S256", "EX1S1")
EX2 = KeyInfo("ex2", "exchange", "EX2S256", "EX2S1")


def test_tang_config_exact():
    assert tang_config("192.168.1.112", 7500, SIG) == '{"url":"http://192.168.1.112:7500","thp":"SIGS256"}'


def test_tang_config_ipv6_brackets():
    assert tang_config("fe80::1", 7500, SIG) == '{"url":"http://[fe80::1]:7500","thp":"SIGS256"}'


def test_fix_and_test_command_exact():
    cfg = tang_config("192.168.1.112", 7500, SIG)
    assert fix_command(cfg) == f"sudo clevis luks edit -d <disk> -s <slot> -c '{cfg}'"
    assert commands.test_command() == "sudo clevis luks pass -d <disk> -s <slot> >/dev/null && echo OK"


def test_find_steps_mentions_old_address():
    steps = find_steps("192.168.1.50")
    assert steps[0]["command"] == "lsblk -o NAME,FSTYPE,FSVER,MOUNTPOINTS"
    assert "crypto_LUKS" in steps[0]["text"] and "/dev/sda2" in steps[0]["text"]
    assert steps[1]["command"] == "sudo clevis luks list -d <disk>"
    assert "192.168.1.50" in steps[1]["text"]
    assert "with the Home Assistant machine's address" in find_steps(None)[1]["text"]


def _inner(script):
    return script[script.index("'") + 1 : script.rindex("'")]


def test_one_step_script_passes_sh_syntax_check():
    script = one_step_fix_script([EX1, EX2], tang_config("192.168.1.112", 7500, SIG))
    r = subprocess.run(["sh", "-n"], input=_inner(script), text=True, capture_output=True)
    assert r.returncode == 0, r.stderr


def test_one_step_fixes_then_tests_each_binding():
    s = one_step_fix_script([EX1], tang_config("192.168.1.112", 7500, SIG))
    assert 'NEW_TANG_CONFIG="{\\"url\\":\\"http://192.168.1.112:7500\\",\\"thp\\":\\"SIGS256\\"}"' in s
    assert ('clevis luks edit -d "$d" -s "$s" -c "$NEW_TANG_CONFIG" && '
            'clevis luks pass -d "$d" -s "$s" >/dev/null && echo "OK: $d slot $s" || echo "FAILED: $d slot $s"\n') in s
    assert s.startswith("sudo sh -c '")
    luks1 = 'for d in $(blkid -t TYPE=crypto_LUKS -o device); do\n  cryptsetup luksDump "$d" | grep -q "^Version:\\s*1" && { echo "LUKS1 disk, not supported: $d"; continue; }'
    assert luks1 in s
    with pytest.raises(ValueError):
        one_step_fix_script([EX1], "{'a'}")


def test_one_step_contains_both_hashes_of_exchange_keys_only():
    s = one_step_fix_script([SIG, EX1, EX2], tang_config("1.2.3.4", 7500, SIG))
    assert 'TANG_KEY_FINGERPRINT="EX1S256 EX1S1 EX2S256 EX2S1"' in s
    assert "SIGS1" not in s and "SIGS256" not in s.split("NEW_TANG_CONFIG")[0]


def test_one_step_has_no_internal_clevis_functions():
    assert "clevis-luks-common-functions" not in one_step_fix_script([EX1], tang_config("1.2.3.4", 7500, SIG))


def test_device_commands_shape():
    d = device_commands("192.168.1.50", "192.168.1.112", 7500, [SIG, EX1])
    assert set(d) == {"find", "fix", "test", "one_step_fix"}
    assert "SIGS256" in d["fix"] and "EX1S256" in d["one_step_fix"]


def test_commands_shown_after_verification():
    assert commands.COMMANDS_VERIFIED is True


def test_found_set_after_found_echo_not_in_action():
    s = one_step_fix_script([EX1], tang_config("1.2.3.4", 7500, SIG))
    lines = [l.strip() for l in s.splitlines()]
    i = lines.index('echo "Found binding to this Tang server: $d slot $s"')
    assert lines[i + 1] == "found=1"
    assert "found=1" not in lines[i + 2]
    assert lines[i + 2].startswith("clevis luks edit")


@pytest.mark.parametrize("env,expected", [(None, False), ("1", True), ("0", False), ("true", False), ("", False)])
def test_commands_verified_env_override(monkeypatch, env, expected):
    monkeypatch.setattr(commands, "COMMANDS_VERIFIED", False)  # the env var alone decides
    if env is None:
        monkeypatch.delenv("TANG_COMMANDS_VERIFIED", raising=False)
    else:
        monkeypatch.setenv("TANG_COMMANDS_VERIFIED", env)
    assert commands.commands_verified() is expected


def test_commands_verified_follows_constant(monkeypatch):
    monkeypatch.delenv("TANG_COMMANDS_VERIFIED", raising=False)
    monkeypatch.setattr(commands, "COMMANDS_VERIFIED", True)
    assert commands.commands_verified() is True


def test_bind_command():
    assert commands.bind_command('{"url":"http://1.2.3.4:7500","thp":"X"}') == (
        "sudo clevis luks bind -d <disk> tang '{\"url\":\"http://1.2.3.4:7500\",\"thp\":\"X\"}'")
