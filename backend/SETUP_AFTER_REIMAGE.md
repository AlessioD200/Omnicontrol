# Omnicontrol Hub Reimage Playbook

This guide walks through bringing a freshly flashed Raspberry Pi OS Lite installation back to a fully functional Omnicontrol hub.

## 1. Flash, boot, and network
1. Flash Raspberry Pi OS Lite (64-bit recommended) to the microSD card.
2. Before ejecting, drop an empty file named `ssh` on the boot partition to enable SSH.
3. (Optional) Add `wpa_supplicant.conf` for Wi-Fi credentials.
4. Boot the Pi, locate its IP (router UI or `ping raspberrypi.local`).

## 2. Bootstrap the hub
SSH into the Pi as the default user (`pi` or the username you configured) and run:

```bash
curl -sSL https://raw.githubusercontent.com/<your-org>/Omnicontrol/main/backend/scripts/bootstrap_pi.sh | sudo bash
```

Environment variables accepted by the script:
- `OMNICONTROL_USER` — default `omnicontrol`
- `REPO_URL` — fork URL if you maintain a fork

The script will:
- Ensure the `omnicontrol` user exists
- Install apt dependencies (BlueZ, ffmpeg, build tools, Python tooling)
- Clone or update the repository to `/home/omnicontrol/Omnicontrol`
- Create and populate the `.venv` virtual environment under `backend/`
- Install systemd units and start both `omnicontrol.service` and the BLE agent

## 3. Verify services

```bash
sudo systemctl status omnicontrol.service
sudo systemctl status omnicontrol-agent.service
sudo journalctl -u omnicontrol.service -n 100 --no-pager
```

## 4. Pair Bluetooth / BLE devices
Use the mobile app pairing flow or trigger it via API:

```bash
curl -X POST http://<hub-ip>:8000/api/pairings/jobs \
  -H "Content-Type: application/json" \
  -d '{"address":"AA:BB:CC:DD:EE:FF","name":"Living Room TV"}'
```

Poll job status:

```bash
curl http://<hub-ip>:8000/api/pairings/jobs/<job-id>
```

If you are near the Pi, you can also run the CLI helper shipped in the repo:

```bash
sudo -u omnicontrol -H bash -c 'cd /home/omnicontrol/Omnicontrol/backend && ./test_pair.sh AA:BB:CC:DD:EE:FF'
```

## 5. Register IP cameras
Fill in the camera/RTSP credentials and run the helper script (from any machine with network reachability to the hub):

```bash
cd backend/scripts
./register_camera.sh \
  --hub http://<hub-ip>:8000 \
  --id living-room-cam \
  --name "Living Room Cam" \
  --ip 192.168.0.236 \
  --username camerauser \
  --password ALEdpr11 \
  --path stream1
```

Once registered, test playback:

```bash
curl -v http://<hub-ip>:8000/api/devices/living-room-cam/hls -o /tmp/stream.m3u8
```

## 6. Link mobile app users
Use the account-link endpoint to tie a local hub to a mobile user token:

```bash
curl -X POST http://<hub-ip>:8000/api/account/link \
  -H "Content-Type: application/json" \
  -d '{"user_id":"alice","token":"<app-issued-token>","hub":"http://<hub-ip>:8000"}'
```

## 7. Deploy mobile app (Flutter)
1. Install Flutter SDK (3.19+ recommended) on your workstation.
2. Connect a device/emulator; run `flutter doctor` to confirm toolchain health.
3. Inside the `mobile_app/` folder:

```bash
flutter pub get
flutter run # or flutter build apk
```

The app is pre-configured to point to `http://localhost:8000` for development. Update the `lib/config/app_config.dart` file to set your hub address when testing on device.

## 8. Maintenance commands
- Restart backend: `sudo systemctl restart omnicontrol.service`
- Tail logs: `sudo journalctl -f -u omnicontrol.service`
- Update hub software (from repo root):

```bash
sudo -u omnicontrol -H bash -c '
  cd /home/omnicontrol/Omnicontrol &&
  git pull &&
  source backend/.venv/bin/activate &&
  pip install -r backend/requirements.txt &&
  sudo systemctl restart omnicontrol.service
'
```

## 9. Troubleshooting quick hits
- **No Bluetooth adapter:** check `lsusb` / `hciconfig`, ensure `bluetooth` service is running.
- **Pairing stuck:** restart `omnicontrol-agent.service` and ensure the device is in pairing mode.
- **RTSP 401:** confirm the Tapo camera account credentials and that RTSP is enabled in the Tapo app.
- **HLS manifest empty:** run `journalctl -u omnicontrol.service` for ffmpeg logs, verify network reachability to the camera.

Keep this guide alongside the SD-card image so a reimage is only a single script away.
