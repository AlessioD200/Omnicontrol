Omnicontrol — Raspberry Pi setup
================================

This file documents a reproducible setup for running the Omnicontrol backend and the BlueZ agent runner on a Raspberry Pi.

Assumptions
- You have a user `omnicontrol` on the Pi and the project is checked out to `/home/omnicontrol/Omnicontrol`.
- A Python virtualenv exists at `/home/omnicontrol/Omnicontrol/backend/.venv` with the required deps installed.

Quick steps
-----------

1) Create user (if needed):

    sudo adduser --disabled-password --gecos '' omnicontrol

2) Install system deps & Python venv:

    sudo apt update
    sudo apt install -y python3-venv python3-pip bluez bluetooth libdbus-1-dev gcc

    sudo -u omnicontrol -H bash -c '
      cd /home/omnicontrol/Omnicontrol/backend
      python3 -m venv .venv
      source .venv/bin/activate
      pip install --upgrade pip
      pip install -r requirements.txt
    '

3) Copy systemd unit files into place and enable them:

    sudo cp backend/systemd/omnicontrol.service /etc/systemd/system/
    sudo cp backend/systemd/omnicontrol-agent.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now omnicontrol-agent.service
    sudo systemctl enable --now omnicontrol.service

4) Verify services:

    sudo systemctl status omnicontrol.service
    sudo systemctl status omnicontrol-agent.service

5) Test pairing flow (on the Pi):

    cd /home/omnicontrol/Omnicontrol/backend
    ./test_pair.sh 78:BD:BC:96:AC:07 "My TV"

Notes and troubleshooting
- If the DBus agent import fails (dbus-next incompatibility), the agent runner will fall back to starting an interactive `bluetoothctl` process and registering an agent there. This usually enables headless pairing.
- If your device shows a passkey & requires confirmation, set the agent capability in the systemd unit `Environment="OMNICONTROL_BLUEZ_AGENT_CAP=DisplayYesNo"` and restart the agent unit.
- If the backend service is bound to localhost only, the systemd unit above forces `uvicorn` to bind to 0.0.0.0 so the hub is reachable from your LAN.

If you run into issues, collect these logs and paste them when asking for help:

    sudo journalctl -u omnicontrol.service -n 200 --no-pager
    sudo journalctl -u omnicontrol-agent.service -n 200 --no-pager
    sudo journalctl -u bluetooth -n 200 --no-pager
