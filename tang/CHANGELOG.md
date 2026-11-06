# Changelog

## 0.1.7

- The dashboard no longer shows a stale version after an app update.

## 0.1.6

- Dashboard and docs no longer assume Home Assistant runs on a Raspberry Pi.

## 0.1.5

- The reservation banner shows the Pi's MAC address and the name it likely has in your router's device list.
- Configuration-tab changes apply within about a minute again, with no restart (reverts 0.1.4's restart requirement).

## 0.1.4

- Configuration-tab changes take effect after restarting the app; the app no longer re-reads its options every
  minute. Dashboard actions (Mark as reserved, Mark as known, Forget) still apply immediately.

## 0.1.3

- Mark as reserved button on the reminder banner (sets the Address reserved option).
- Option changes now apply within a minute without a restart.

## 0.1.2

- App icon, and a working sidebar icon (the previous one didn't exist).
- Devices list: shows each device's own address, and labels the Pi address it reaches Tang at.

## 0.1.1

- Mark devices as known, or forget them, from the dashboard; no restart needed.

## 0.1.0

- First release: Tang server on port 7500, a request log, per-device address checks, Home Assistant entities and a
  `tang_request` event, and an ingress dashboard.
