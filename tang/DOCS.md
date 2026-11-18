# Tang

This add-on runs a [Tang](https://github.com/latchset/tang) server. Devices with LUKS-encrypted disks
use it, through [Clevis](https://github.com/latchset/clevis), to unlock themselves at boot while they are on your
home network. The add-on also logs every request, checks that each device still reaches Home Assistant at the right
address, and shows all of this on a dashboard in the sidebar.

Devices find Tang by the Home Assistant machine's IP address, so that address must never change. Reserve it in your router's DHCP settings
(often called a DHCP reservation or static lease).

Tang listens on port 7500 by default. You can change it in the **Network** section of this app's Configuration
tab. This page writes `<port>` for whichever port you use.

Changing the port later breaks every device you have already bound: each binding stores the full address and port,
so those devices fall back to the password prompt until you update them. The dashboard flags each one (for example
"unlocks via 192.168.1.87:7500, but Tang is now at 192.168.1.87:7600") and shows how to fix it.

Keep that port reachable only from your home network. Do not forward it from the internet.

## Setup

Clevis runs on Linux, so devices must be Linux machines whose disk is encrypted with LUKS2. The dashboard's
**Add a Linux device** section has these steps with this server's details filled in.

1. Reserve the Home Assistant machine's address in your router first, as described above. Then press
   **Mark as reserved** on the yellow banner in the dashboard (or turn on **Address reserved** in this app's
   Configuration).
2. Install Clevis on the device:
   - Debian or Ubuntu: `clevis clevis-luks clevis-initramfs`.
   - Fedora: `clevis clevis-luks clevis-dracut`.
   - Arch: `clevis`. Arch's default boot tool (mkinitcpio) has no built-in Clevis support; the
     [Arch Wiki's Clevis page](https://wiki.archlinux.org/title/Clevis) lists the options.
3. Bind the disk. On the device, run:

   ```sh
   sudo clevis luks bind -d <disk> tang '{"url":"http://<address>:<port>","thp":"<signing fingerprint from the dashboard>"}'
   ```

   `<disk>` is the encrypted partition (find it with `lsblk -o NAME,FSTYPE,FSVER,MOUNTPOINTS`: the
   `crypto_LUKS` row), `<address>` is the Home Assistant machine's reserved address, `<port>` is Tang's port (see
   above), and the signing fingerprint is shown in the dashboard's Keys section. It asks for the disk's password and
   adds a new key slot; the password keeps working.
4. Make sure the boot image includes Clevis and brings up the network, then rebuild it. This depends on the
   distribution: on Debian and Ubuntu, `clevis-initramfs` adds itself (rebuild with `sudo update-initramfs -u`); on
   Fedora, rebuild with `sudo dracut -f` and see Fedora's Clevis documentation for network options such as
   `rd.neednet=1`; on Arch, follow the Arch Wiki page above.
5. Test it (this prints nothing secret and ends with `OK` on success):

   ```
   sudo clevis luks pass -d <disk> -s <slot> >/dev/null && echo OK
   ```

   Find `<slot>` with `sudo clevis luks list -d <disk>`: a freshly bound disk usually shows one `tang` line, and
   the number at its start is the slot.
6. Restart the device. It should unlock without asking for the password. Then find its request in the dashboard's
   history and click **Mark as known** (or list it under **Known devices** ahead of time).

If Tang's address or port changes later, the dashboard flags each device still using the old one, with a
**How to fix** section: one script that points every binding to this Tang server at the current address and tests
it, or step by step for a single binding you pick. Fixing may print `No key available with this passphrase.` before
`Binding edited successfully`; that line is normal (Clevis first checks for an empty password).

## Options

Changes made from the dashboard take effect immediately. Changes made in this app's Configuration tab take effect
within about a minute, with no restart.

- **`known_devices`**: optional. Names of the devices you bound, as your router reports them (for example
  `server.lan`). You can also mark devices known from the dashboard. Requests from other devices are marked unknown.
- **`address_reserved`**: turn on once the Home Assistant machine's address is reserved. The dashboard's **Mark as reserved** button
  sets this for you. This hides the reservation reminder.

## Known and unknown devices

"Known" is a label to help you read the history. It is not a security check. Tang answers every device that can
reach it, known or not. A device counts as known when its name (as your router reports it) or its IP address is on
the known list. Any device on your network can choose the name it gives your router, and can take over another
device's address while that device is offline. So a request marked known could still come from someone else, and
an address you marked known belongs to whichever device gets it next.

What protects your disks is who can reach Tang. Anyone who has a bound disk (or a copy of it) and can reach Tang can
unlock it, including through a guest or smart-home device on your network. Keep guests and untrusted devices on a
separate network that can't reach Tang.

## Home Assistant entities

- `binary_sensor.tang_running`: whether Tang answers.
- `sensor.tang_last_unlock`: the time of the last successful unlock, and which device it was.
- `sensor.tang_last_unknown_request`: the time of the last request from a device that isn't known.
- `binary_sensor.tang_<device>_address_ok`: off when a device last reached Tang at an address or port that no longer
  reaches it.

Every request also fires a `tang_request` event, which you can use in automations. Its data holds `device`,
`known`, `ip`, `kind` (`adv` for fetching keys, `rec` for an unlock, `other` for anything else), `status` (the HTTP
status, `200` on success) and `host`.

### Get notified of every unlock

A successful unlock (`kind: rec`, `status: 200`) happens when a bound device boots, or when you run a test or fix
command on it. That makes it a better signal than the known label: you can tell whether you expected it. To get a phone notification for each one, create an
automation and paste this in the editor's **Edit in YAML** mode, replacing `mobile_app_your_phone` with your own
notify action:

```yaml
alias: Tang unlock
triggers:
  - trigger: event
    event_type: tang_request
    event_data:
      kind: rec
      status: 200
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Tang unlock
      message: "{{ trigger.event.data.device }} ({{ trigger.event.data.ip }}) unlocked its disk."
mode: queued
```

## Keys

The keys live in the add-on's `/data/keys` and are included in Home Assistant backups. Anyone with a copy of them can
unlock your devices while on a network that can reach them, so keep backups private.
