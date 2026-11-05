# Tang add-on

A Home Assistant add-on that runs a [Tang](https://github.com/latchset/tang) server, so Linux machines with
Clevis-bound LUKS disks can unlock themselves at boot while they are on your home network. It also keeps a log of
every request, shows a dashboard in the Home Assistant sidebar, and publishes entities for automations.

## Install

1. In Home Assistant, go to Settings -> Apps and select Install app. (Before Home Assistant 2026.2, apps were
   called add-ons: Settings -> Add-ons -> Add-on Store.)
2. Open the menu (three dots, top right) -> Repositories, paste this repository's URL and select Add:
   `https://github.com/eyuelt/ha-tang-addon`
3. Install "Tang" from the store and start it.

## Security

Tang must only be reachable from your home network. Do not port-forward port 7500 from your router.

## Documentation

See [tang/DOCS.md](tang/DOCS.md) for setup and usage.
