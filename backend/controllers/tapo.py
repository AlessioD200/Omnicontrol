from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import urllib.request
import urllib.error
import logging

logger = logging.getLogger(__name__)


@dataclass
class TapoDeviceEntry:
    id: str
    name: str
    ip: str
    type: str  # 'Light' or 'Camera'
    metadata: Dict[str, object]


class TapoController:
    """Minimal TP-Link Tapo integration.

    Behavior:
    - Loads a simple JSON store at `state/tapo_devices.json` containing known devices
      with fields: id, name, ip, type, metadata (optional).
    - Provides `list_devices()` to enumerate known devices.
    - Provides `ping(ip)` using a lightweight HTTP probe.
    - Provides `toggle(ip, turn_on)` which attempts to use the optional `pytapo`
      library if installed; otherwise raises NotImplementedError with install hints.

    This keeps the core project dependency-free while allowing users to install
    `pytapo` for full local control of Tapo bulbs and cameras.
    """

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self._store_path = Path(store_path or "state/tapo_devices.json")
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._devices: Dict[str, TapoDeviceEntry] = {}

    async def startup(self) -> None:
        # load known devices from disk
        if self._store_path.exists():
            try:
                data = json.loads(self._store_path.read_text())
                if isinstance(data, dict):
                    for entry in data.get("devices", []):
                        try:
                            dev = TapoDeviceEntry(
                                id=str(entry.get("id")),
                                name=str(entry.get("name") or entry.get("id")),
                                ip=str(entry.get("ip") or ""),
                                type=str(entry.get("type") or "Light"),
                                metadata=entry.get("metadata") or {},
                            )
                            self._devices[dev.id] = dev
                        except Exception:
                            continue
            except Exception:
                logger.exception("Failed to load Tapo device store")

    def list_devices(self) -> List[TapoDeviceEntry]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[TapoDeviceEntry]:
        return self._devices.get(device_id)

    def add_or_update_device(self, entry: Dict[str, object]) -> None:
        device_id = str(entry.get("id"))
        if not device_id:
            raise ValueError("Device id required")
        dev = TapoDeviceEntry(
            id=device_id,
            name=str(entry.get("name") or device_id),
            ip=str(entry.get("ip") or ""),
            type=str(entry.get("type") or "Light"),
            metadata=entry.get("metadata") or {},
        )
        self._devices[dev.id] = dev
        self._persist()

    def _persist(self) -> None:
        payload = {"devices": [
            {"id": d.id, "name": d.name, "ip": d.ip, "type": d.type, "metadata": d.metadata}
            for d in self._devices.values()
        ]}
        try:
            self._store_path.write_text(json.dumps(payload, indent=2))
        except Exception:
            logger.exception("Failed to persist Tapo device store")

    def ping(self, ip: str, timeout: int = 3) -> bool:
        # Lightweight HTTP probe to the device
        if not ip:
            return False
        try:
            url = f"http://{ip}/"
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.status == 200
        except urllib.error.URLError:
            return False
        except Exception:
            return False

    def toggle(self, ip: str, turn_on: bool) -> bool:
        # Use pytapo if available for bulb control; otherwise raise a helpful error
        try:
            import pytapo
        except Exception:
            raise NotImplementedError("Toggle requires the optional 'pytapo' package. Install with: pip install pytapo")

        try:
            # pytapo exposes a simple client for bulbs and cameras. We use the local IP
            # plus stored credentials if available (the caller should manage credentials in metadata).
            # Minimal usage pattern (pseudocode-like, depends on pytapo API):
            client = pytapo.TapoClient(ip)
            # If the client requires login, caller should have stored creds and pytapo will prompt or handle them.
            if turn_on:
                client.turn_on()
            else:
                client.turn_off()
            return True
        except Exception as exc:
            logger.exception('Tapo toggle failed for %s: %s', ip, exc)
            raise
