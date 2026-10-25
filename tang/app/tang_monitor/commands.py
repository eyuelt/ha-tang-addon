"""Shell commands the user runs ON the encrypted device to repoint a Clevis Tang binding."""
import json
from typing import Literal

from .keys import KeyInfo

# Hidden in the dashboard until the commands are verified on a real disk.
COMMANDS_VERIFIED: bool = False


def tang_config(pi_address: str, port: int, signing: KeyInfo) -> str:
    host = f"[{pi_address}]" if ":" in pi_address else pi_address
    return json.dumps({"url": f"http://{host}:{port}", "thp": signing.s256}, separators=(",", ":"))


def find_steps(old_address: str | None) -> list[dict]:
    which = old_address if old_address else "this Pi's address"
    return [
        {
            "text": (
                "Find the encrypted disk. Look for the row whose FSTYPE is crypto_LUKS (FSVER 2 is LUKS2). "
                "Prefix its NAME with /dev/, so sda2 becomes /dev/sda2. That is your <disk>."
            ),
            "command": "lsblk -o NAME,FSTYPE,FSVER,MOUNTPOINTS",
        },
        {
            "text": (
                f"Find the binding's slot. Pick the line that says tang with {which}. "
                "The number at the start of that line is your <slot>."
            ),
            "command": "sudo clevis luks list -d <disk>",
        },
    ]


def fix_command(config: str) -> str:
    return f"sudo clevis luks edit -d <disk> -s <slot> -c '{config}'"


def test_command() -> str:
    return "sudo clevis luks pass -d <disk> -s <slot> >/dev/null && echo OK"


_TEMPLATE = r"""sudo sh -c '
TANG_KEY_FINGERPRINT="{fingerprints}"
{config_line}found=0
for d in $(blkid -t TYPE=crypto_LUKS -o device); do
  cryptsetup luksDump "$d" | grep -q "^Version:\s*1" && {{ echo "LUKS1 disk, not supported: $d"; continue; }}
  for t in $(seq 0 31); do
    tok=$(cryptsetup token export --token-id $t "$d" 2>/dev/null) || continue
    [ "$(echo "$tok" | jose fmt -j- -g type -u-)" = clevis ] || continue
    kid=$(echo "$tok" | jose fmt -j- -g jwe -g protected -u- | jose b64 dec -i- | jose fmt -j- -g kid -u-)
    case " $TANG_KEY_FINGERPRINT " in *" $kid "*) ;; *) continue ;; esac
    s=$(echo "$tok" | jose fmt -j- -g keyslots -g 0 -u-)
    echo "Found binding to this Tang server: $d slot $s"
    found=1
    {action}
  done
done
[ $found = 1 ] || echo "No binding to this Tang server found"
'"""

_EDIT_ACTION = 'clevis luks edit -d "$d" -s "$s" -c "$NEW_TANG_CONFIG"'
_TEST_ACTION = (
    'clevis luks pass -d "$d" -s "$s" >/dev/null && echo "OK: $d slot $s" '
    '|| echo "FAILED: $d slot $s"'
)


def one_step_script(
    mode: Literal["edit", "test"], exchange_keys: list[KeyInfo], config: str | None = None
) -> str:
    fingerprints = " ".join(f"{k.s256} {k.s1}" for k in exchange_keys if k.use == "exchange")
    if mode == "edit":
        if config is None:
            raise ValueError("edit mode requires a config")
        if "'" in config:
            raise ValueError("config must not contain single quotes")
        escaped = config.replace("\\", "\\\\").replace('"', '\\"')
        config_line = f'NEW_TANG_CONFIG="{escaped}"\n'
        action = _EDIT_ACTION
    else:
        config_line = ""
        action = _TEST_ACTION
    return _TEMPLATE.format(fingerprints=fingerprints, config_line=config_line, action=action)


def device_commands(old_address: str, pi_address: str, port: int, keys: list[KeyInfo]) -> dict:
    signing = next(k for k in keys if k.use == "signing")
    exchange = [k for k in keys if k.use == "exchange"]
    config = tang_config(pi_address, port, signing)
    return {
        "find": find_steps(old_address),
        "fix": fix_command(config),
        "test": test_command(),
        "one_step_fix": one_step_script("edit", exchange, config),
        "one_step_test": one_step_script("test", exchange),
    }
