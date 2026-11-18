# Design notes

Why this add-on works the way it does. For setup and usage, see [tang/DOCS.md](../tang/DOCS.md).

## The problem

An always-on Linux server with a LUKS-encrypted disk stops at the disk password prompt on every reboot, before
networking starts. Nothing on it is reachable until someone connects a monitor and types the password, which
defeats the point of a server that should come back from updates and power blips by itself.

- **TPM auto-unlock** needs a TPM, which older hardware (for example older Mac minis) doesn't have.
- **A key file in the boot image** unlocks the disk anywhere, so a stolen machine unlocks too. That gives up what
  the encryption is for.
- **Network-bound disk encryption** (Clevis with a Tang server) unlocks the disk only while the machine can reach a
  Tang server at home. A stolen machine can't reach it and asks for the password.

Tang needs another always-on device at home. A Home Assistant machine already is one, but Home Assistant OS can't
install software the usual way, so Tang runs as an add-on.

## Principles

- **Nothing gets worse than a plain encrypted disk.** If Tang can't be reached, the device shows its normal password
  prompt, and the password always works. Binding adds a key slot and leaves the password slot alone.
- **No custom code in the boot path.** The device side uses its distribution's packaged Clevis hooks and
  configuration only. A boot image that hangs before the password prompt is the worst possible outcome, and
  hand-written initramfs code is the likeliest way to get one.
- **Try once at boot, then ask for the password.** No retrying or waiting for Tang. After a power outage, the Home
  Assistant machine may still be booting when the device asks; the device then falls back to the password prompt.
  A wait would need custom boot code.
- **Never unlock away from home.** No keys stored on the boot partition or anywhere else on the device.
- **Tang serves only the home network.** It is never exposed to the internet.
- **No secrets in the repository.** Tang's keys are generated at first start and never leave the add-on's data
  folder (and Home Assistant backups of it).

## Binding by IP address, not by name

Bindings point at the Home Assistant machine's IP address, so the address has to be reserved in the router. Names
were the first choice, but they often don't resolve in the initramfs:

- Boot-time network hooks (for example mkinitcpio's `netconf`) get DNS servers from DHCP but don't write
  `/etc/resolv.conf`.
- Copying the host's `/etc/resolv.conf` into the boot image doesn't help when it points at the `systemd-resolved`
  stub (`127.0.0.53`), which doesn't run in the initramfs.
- `.local` names need mDNS, which isn't available there either.

The binding also includes the signing key's thumbprint (`thp`), so Clevis doesn't ask whether to trust the key.

## The address check

A device stores Tang's full address and port in its binding. If the Home Assistant machine's address or Tang's port
changes, that device falls back to the password prompt on its next boot.

The add-on can't read the router's reservations, so it checks for the consequence instead:

- **What it stores:** for each device, the address and port it used on its last successful request (from the
  request's `Host` header). This is kept indefinitely, separately from the request history, because a device that
  rarely reboots may not ask again for months.
- **What it compares:** each stored address against the Home Assistant machine's current addresses. Any match passes,
  since the machine can have several (IPv4, IPv6, more than one interface). The check works without a new request
  from the device, because once the address has moved, the device's requests can't arrive.
- **What it proves:** a match means "the address hasn't changed since this device last reached it". It doesn't
  prove the reservation exists, and the wording on the dashboard doesn't claim it does.
- **What it can't do:** if both machines reboot at the same time and the address changes, the device is already at
  the password prompt before the add-on can flag anything. The flag then explains why.

The flag stays until it's resolved:

- **Flagged** when a device's stored address no longer matches. A few consecutive mismatching checks are needed, so
  a brief network change doesn't flag anything.
- **"I've fixed it"** moves it to "fixed, not yet tested".
- **Cleared** only when the device makes a successful request to a current address, so a fix that didn't work
  stays visible.
- **Forget** removes a retired device.

## Device-side commands

The dashboard shows the commands to run on a device, with everything the add-on knows filled in (address, port,
signing thumbprint). Only the device's disk and key slot are left as placeholders, with steps to find them.

- **The test command hides its output.** `clevis luks pass` prints the slot's unlock secret, so its output goes to
  `/dev/null`. It runs the same Tang exchange as boot, without rebooting. It doesn't test the boot-time network; only
  a restart does.
- **Fixing doesn't need a new boot image.** The binding lives in the LUKS header.
- **The fix-and-test script finds bindings by key, not by address.** It matches each Clevis token's `kid` against
  this server's exchange-key thumbprints (SHA-256 and SHA-1, since older Clevis versions used SHA-1), so it works
  even when a binding points at a wrong address.
- **Public interfaces only.** The script uses `cryptsetup`, `jose` and Clevis's LUKS2 token format, not Clevis's
  internal shell functions, which can change between versions. LUKS1 isn't supported.
- **Verified before shown.** The commands are run against a real LUKS2 binding before the dashboard shows them.

## Request log and dashboard

Tang doesn't keep a history, so the add-on accepts each connection itself, hands it to a fresh `tangd` process (the
way Tang is normally run from a socket), and records the client address, time, request type (fetching keys at bind
time, or an unlock request at boot) and result. The history is bounded to the most recent 500 requests.

Devices are named through the router's reverse DNS. "Known" is a reading aid, not a security check: Tang answers
anyone who can reach it.

The dashboard can't tell whether a device finished booting, only that its unlock request was answered, so it says
that and nothing more.

## Entities

The add-on writes its entities through the Home Assistant API and rewrites them on start and every minute. They
aren't registry entities, so they can't be renamed in the UI and briefly disappear when Home Assistant restarts.
MQTT discovery would avoid that, but it would require an MQTT broker and integration that many setups don't have.

## Keys

Keys are generated at first start in the add-on's `/data`, so they're included in Home Assistant backups and a
restored machine keeps working with existing bindings. If the keys are ever lost, devices fall back to the password
prompt and can be bound again; nothing is locked out. Key rotation isn't supported yet.

## Arch Linux (mkinitcpio) notes

This add-on was first used with an Arch-based device using mkinitcpio and the Limine bootloader. Choices made there:

- **Hook:** `mkinitcpio-clevis-hook` from the AUR. It was written with TPM in mind and its messages say "TPM", but
  its run hook calls `clevis-luks-unlock`, which handles the Tang pin. It goes immediately before `encrypt`, and
  `curl` is added to the boot image because the Tang pin needs it.
- **Network:** `netconf` (from `mkinitcpio-netconf`) rather than `net`. Its DHCP attempt is bounded by the
  `netconf_timeout` kernel parameter, so an unplugged cable doesn't delay the password prompt by much, and its
  cleanup hook takes the interface down before the real system starts, so nothing lingers.
- **Surviving updates:** distribution-managed mkinitcpio config files aren't edited in place. The Clevis changes go
  in a separate `mkinitcpio.conf.d` file that sorts last and adds to the existing hook list rather than copying it.
- **Plymouth:** plain `encrypt` with the `plymouth` hook keeps the graphical password prompt when Tang fails.
- **Before the first reboot:** confirm the password still unlocks (`cryptsetup open --test-passphrase`) and have a
  snapshot or other way back.
