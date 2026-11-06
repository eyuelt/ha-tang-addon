# Tang

This add-on runs a [Tang](https://github.com/latchset/tang) server on port 7500. Devices with LUKS-encrypted disks
use it, through [Clevis](https://github.com/latchset/clevis), to unlock themselves at boot while they are on your
home network. The add-on also logs every request, checks that each device still reaches the Pi at the right
address, and shows all of this on a dashboard in the sidebar.

Devices find Tang by the Pi's IP address, so that address must never change. Reserve it in your router's DHCP settings
(often called a DHCP reservation or static lease).

Keep port 7500 reachable only from your home network. Do not forward it from the internet.

## Setup

1. Reserve the Pi's address in your router first, as described above. Then press
   **Mark as reserved** on the yellow banner in the dashboard (or turn on **Address reserved** in this app's
   Configuration).
2. Open the Tang panel, find the device's request in the history, and click **Mark as known**. No restart is needed.
   (The **Known devices** option still works for listing devices ahead of time. Option changes apply within a
   minute, with no restart.)
3. Bind a device. On the device, run:

   ```sh
   sudo clevis luks bind -d <disk> tang '{"url":"http://<pi-address>:7500","thp":"<signing fingerprint from the dashboard>"}'
   ```

   `<disk>` is the encrypted partition (for example `/dev/nvme0n1p2`), `<pi-address>` is the Pi's reserved address,
   and the signing fingerprint is shown in the dashboard's Keys section.
4. Test it (this prints nothing secret and ends with `OK` on success):

   ```
   sudo clevis luks pass -d <disk> -s <slot> >/dev/null && echo OK
   ```

   Find `<disk>` with `lsblk -o NAME,FSTYPE,FSVER,MOUNTPOINTS` and `<slot>` with `sudo clevis luks list -d <disk>`.
   The dashboard's "How to test" and "How to fix" sections will appear in a later version, once the commands
   have been verified.

## Options

- **`known_devices`**: optional. Names of the devices you bound, as your router reports them (for example
  `server.lan`). Changes apply within a minute, with no restart. You can also mark devices known from the dashboard. Requests from
  other devices are marked unknown.
- **`address_reserved`**: turn on once the Pi's address is reserved. The dashboard's **Mark as reserved** button
  sets this for you. This hides the reservation reminder.

## Home Assistant entities

- `binary_sensor.tang_running`: whether Tang answers.
- `sensor.tang_last_unlock`: the time of the last successful unlock, and which device it was.
- `sensor.tang_last_unknown_request`: the time of the last request from a device not in `known_devices`.
- `binary_sensor.tang_<device>_address_ok`: off when a device last reached the Pi at an address the Pi no longer
  has.

Every request also fires a `tang_request` event, which you can use in automations.

## Keys

The keys live in the add-on's `/data/keys` and are included in Home Assistant backups. Anyone with a copy of them can
unlock your devices while on a network that can reach them, so keep backups private.
