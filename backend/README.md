# Omnicontrol Raspberry Pi Backend

This FastAPI service exposes Omnicontrol hub capabilities so the web app can talk to real hardware on a Raspberry Pi.

## Install dependencies

```bash
cd /path/to/Omnicontrol/backend
python3 -m venv .venv
source .venv/bin/activate
python3 -m http.server 8080
pip install -r requirements.txt
```

## Run the service

```bash
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API listens on port `8000`. Point the front-end `script/app.js` to `http://<pi-ip>:8000`.

## Configure protocols

### Bluetooth displays

Bleak handles all Bluetooth LE interactions. Export the MAC address of any display you want to seed into the dashboard and, optionally, the writable characteristic that toggles power:

```bash
export OMNICONTROL_DISPLAY_BT_ADDR=AA:BB:CC:DD:EE:FF
export OMNICONTROL_DISPLAY_POWER_CHAR=0000fff1-0000-1000-8000-00805f9b34fb  # optional
```

When `/api/devices/{id}/toggle` is called the backend writes `0x01`/`0x00` to that characteristic.

### HomeKit accessories

The service uses `aiohomekit` and persists pairings inside `state/homekit.json`. Pair your HomeKit bridge/accessory once and the backend will surface every service exposing an `On` characteristic (lightbulbs, switches, outlets).

Example pairing flow:

```bash
source .venv/bin/activate
python -m aiohomekit discover
python -m aiohomekit pair --alias livingroom --pin 111-22-333
```

The created alias appears in `state/homekit.json`. You can edit or remove pairings with the same CLI (`python -m aiohomekit --help`).

## Optional systemd unit

Create `/etc/systemd/system/omnicontrol.service`:

```
[Unit]
Description=Omnicontrol Hub API
After=network.target bluetooth.service

[Service]
Type=simple
WorkingDirectory=/path/to/Omnicontrol/backend
ExecStart=/path/to/Omnicontrol/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=on-failure
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now omnicontrol.service
```

## API overview

- `GET /api/health` simple health probe.
- `GET /api/devices` list known devices.
- `POST /api/scan` refresh Bleak discovery and sync paired HomeKit accessories.
- `POST /api/devices/{id}/toggle` toggle power state.
- `POST /api/devices/{id}/ping` pulse a device.
- `GET /api/settings` read hub settings.
- `POST /api/settings` persist settings.
- `GET /api/stats` aggregated counts.
- `GET /api/updates/history` release log.
- `POST /api/updates` stage firmware update (stores in `state/updates`).

State lives in the `state/` directory beside this backend (`devices.json`, `settings.json`, `update-history.json`, and `homekit.json`).
