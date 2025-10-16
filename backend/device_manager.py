from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from controllers import BluetoothController, HomeKitController, TapoController
import logging

STATE_VERSION = 1
SCAN_TIMEOUT = int(os.getenv("OMNICONTROL_SCAN_TIMEOUT", "12"))
DEVICE_STATE_FILE = Path(os.getenv("OMNICONTROL_DEVICE_STORE", "state/devices.json"))
SETTINGS_FILE = Path(os.getenv("OMNICONTROL_SETTINGS_STORE", "state/settings.json"))
UPDATE_HISTORY_FILE = Path(os.getenv("OMNICONTROL_UPDATE_STORE", "state/update-history.json"))
HOMEKIT_STORE_FILE = Path(os.getenv("OMNICONTROL_HOMEKIT_STORE", "state/homekit.json"))

DEFAULT_DISPLAY_ADDRESS = os.getenv("OMNICONTROL_DISPLAY_BT_ADDR")
DEFAULT_DISPLAY_POWER_CHAR = os.getenv("OMNICONTROL_DISPLAY_POWER_CHAR")


@dataclass
class Device:
    id: str
    name: str
    type: str
    room: str
    protocols: List[str]
    integrations: List[str]
    status: str = "offline"
    last_seen: str = "Unknown"
    firmware: str = "Unknown"
    address: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["protocols"] = sorted(set(self.protocols))
        payload["integrations"] = sorted(set(self.integrations))
        if payload.get("address") is None:
            payload.pop("address", None)
        if not payload.get("metadata"):
            payload["metadata"] = {}
        # Expose paired/trusted at top level for UI convenience
        metadata = payload.get("metadata") or {}
        payload["paired"] = bool(metadata.get("paired", False))
        payload["trusted"] = bool(metadata.get("trusted", False))
        return payload

    @classmethod
    def from_dict(cls, entry: Dict[str, object]) -> "Device":
        return cls(
            id=entry["id"],
            name=entry.get("name", "Unknown"),
            type=entry.get("type", "Unknown"),
            room=entry.get("room", "Unknown"),
            protocols=entry.get("protocols", []),
            integrations=entry.get("integrations", []),
            status=entry.get("status", "offline"),
            last_seen=entry.get("last_seen", "Unknown"),
            firmware=entry.get("firmware", "Unknown"),
            address=entry.get("address"),
            metadata=entry.get("metadata", {}) or {},
        )


class DeviceManager:
    def __init__(self) -> None:
        self.devices: Dict[str, Device] = {}
        # pairing jobs: job_id -> {status, device_id, error, started_at, finished_at}
        self._pairing_jobs: Dict[str, Dict[str, object]] = {}
        self._state_path = DEVICE_STATE_FILE
        self._settings_path = SETTINGS_FILE
        self._update_history_path = UPDATE_HISTORY_FILE
        self.bluetooth = BluetoothController()
        self.homekit = HomeKitController(HOMEKIT_STORE_FILE)
        self.tapo = TapoController()
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._update_history_path.parent.mkdir(parents=True, exist_ok=True)

    async def startup(self) -> None:
        await asyncio.gather(
            self._load_devices(),
            self._load_defaults(),
            self._load_update_history(),
            self.homekit.startup(),
            self.tapo.startup(),
        )
        await self._refresh_homekit_cache()

    async def _load_devices(self) -> None:
        if not self._state_path.exists():
            self.devices = self._seed_default_devices()
            if self.devices:
                await self._persist_devices()
            return
        try:
            data = json.loads(self._state_path.read_text())
            version = data.get("version", 0)
            devices = data.get("devices", [])
            if version != STATE_VERSION or not isinstance(devices, list):
                raise ValueError("Invalid device store format")
            self.devices = {entry["id"]: Device.from_dict(entry) for entry in devices}
        except Exception:
            self.devices = self._seed_default_devices()

    def _seed_default_devices(self) -> Dict[str, Device]:
        devices: Dict[str, Device] = {}
        if DEFAULT_DISPLAY_ADDRESS:
            metadata: Dict[str, object] = {}
            if DEFAULT_DISPLAY_POWER_CHAR:
                metadata["ble_power_char"] = DEFAULT_DISPLAY_POWER_CHAR
            devices["display-living-tv"] = Device(
                id="display-living-tv",
                name="LG OLED Gallery",
                type="Display",
                room="Living room",
                protocols=["bluetooth"],
                integrations=["scene"],
                status="offline",
                last_seen="Seed",
                firmware="Unknown",
                address=DEFAULT_DISPLAY_ADDRESS,
                metadata=metadata,
            )
        return devices

    async def _persist_devices(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "devices": [device.to_dict() for device in self.devices.values()],
            "saved_at": datetime.utcnow().isoformat(),
        }
        self._state_path.write_text(json.dumps(payload, indent=2))

    async def _refresh_homekit_cache(self) -> List[Device]:
        try:
            homekit_devices = await self.homekit.list_devices()
        except Exception:
            return []

        if not homekit_devices:
            return []

        now = datetime.utcnow().isoformat()
        updated = False
        new_devices: List[Device] = []
        for accessory in homekit_devices:
            metadata = {
                "pairing_id": accessory.pairing_id,
                "aid": accessory.aid,
                "iid": accessory.iid,
                "is_on": accessory.is_on,
            }
            status = "online" if accessory.is_on else "offline"
            existing = self.devices.get(accessory.identifier)
            if existing:
                existing.name = accessory.name
                existing.room = accessory.room
                existing.protocols = ["homekit"]
                existing.integrations = sorted(set(existing.integrations + ["homekit"]))
                existing.metadata.update(metadata)
                existing.status = status
                existing.last_seen = now
            else:
                new_device = Device(
                    id=accessory.identifier,
                    name=accessory.name,
                    type="Accessory",
                    room=accessory.room,
                    protocols=["homekit"],
                    integrations=["homekit"],
                    status=status,
                    last_seen=now,
                    firmware="Unknown",
                    metadata=metadata,
                )
                self.devices[accessory.identifier] = new_device
                new_devices.append(new_device)
            updated = True

        if updated:
            await self._persist_devices()
        return new_devices

    async def _load_defaults(self) -> None:
        if not self._settings_path.exists():
            default_settings = {
                "hubName": "Omnicontrol Hub",
                "room": "Home",
                "networkSsid": "Omnicontrol Mesh",
                "homekitCode": "111-11-111",
                "autoUpdate": True,
                "remoteAccess": False,
                "defaultScene": "evening",
                "cameraRetention": 7,
            }
            self._settings_path.write_text(json.dumps(default_settings, indent=2))

    async def _load_update_history(self) -> None:
        if not self._update_history_path.exists():
            seed = [
                {
                    "version": "1.0.0",
                    "description": "Initial public release – Bluetooth display control + dashboard.",
                    "date": "2025-09-12",
                },
                {
                    "version": "0.9.5-beta",
                    "description": "Added HomeKit bridge discovery and IR recording helpers.",
                    "date": "2025-07-01",
                },
            ]
            self._update_history_path.write_text(json.dumps(seed, indent=2))

    async def get_devices(self) -> List[Dict[str, object]]:
        await self._refresh_homekit_cache()
        # Include known Tapo devices from the TapoController store
        tapo_list = []
        try:
            for td in self.tapo.list_devices():
                dev = Device(
                    id=f"tapo-{td.id}",
                    name=td.name,
                    type=td.type,
                    room="Tapo",
                    protocols=["tapo"],
                    integrations=["tapo"],
                    status="offline",
                    last_seen="Never",
                    firmware="Unknown",
                    address=td.ip,
                    metadata=td.metadata,
                )
                tapo_list.append(dev)
        except Exception:
            tapo_list = []

        combined = list(self.devices.values()) + tapo_list
        return [device.to_dict() for device in combined]

    async def get_device(self, device_id: str) -> Optional[Device]:
        device = self.devices.get(device_id)
        if device:
            return device

        # Support looking up tapo devices whose ids are stored as 'tapo-<id>'
        # by constructing a lightweight Device from the TapoController store.
        if device_id.startswith("tapo-"):
            tid = device_id[5:]
            td = self.tapo.get_device(tid)
            if td:
                return Device(
                    id=device_id,
                    name=td.name,
                    type=td.type,
                    room="Tapo",
                    protocols=["tapo"],
                    integrations=["tapo"],
                    status="offline",
                    last_seen="Never",
                    firmware="Unknown",
                    address=td.ip,
                    metadata=td.metadata,
                )
        return None

    async def connect_device(self, device_id: str) -> bool:
        device = self.devices.get(device_id)
        if not device:
            raise ValueError("Unknown device")
        if not device.address:
            raise ValueError("Device missing address")
        try:
            ok = await self.bluetooth.connect(device.address)
            device.last_seen = datetime.utcnow().isoformat()
            if ok:
                device.status = "online"
            else:
                device.status = "offline"
            await self._persist_devices()
            return ok
        except Exception as exc:
            raise

    async def update_device_metadata(self, device_id: str, metadata: Dict[str, object]) -> Device:
        device = self.devices.get(device_id)
        if not device:
            raise ValueError("Unknown device")
        if not isinstance(metadata, dict):
            raise ValueError("Invalid metadata")
        # Merge metadata
        existing = device.metadata or {}
        existing.update(metadata)
        device.metadata = existing
        # Persist
        await self._persist_devices()
        return device

    async def toggle_device(self, device_id: str) -> Device:
        device = self.devices[device_id]
        now = datetime.utcnow().isoformat()

        if "bluetooth" in device.protocols:
            if not device.address:
                raise ValueError("Bluetooth device missing address")
            target_state = device.status != "online"
            characteristic = device.metadata.get("ble_power_char") or None
            result = await self.bluetooth.toggle_power(
                device.address,
                characteristic=characteristic,
                turn_on=target_state,
            )
            device.status = "online" if result else "offline"
            device.metadata["last_toggle"] = now
        elif "homekit" in device.protocols:
            pairing_id = device.metadata.get("pairing_id")
            aid = device.metadata.get("aid")
            iid = device.metadata.get("iid")
            if pairing_id is None or aid is None or iid is None:
                raise ValueError("HomeKit device missing pairing metadata")
            result = await self.homekit.toggle(pairing_id, aid=int(aid), iid=int(iid))
            device.status = "online" if result else "offline"
            device.metadata.update({"is_on": result, "last_toggle": now})
        elif "tapo" in device.protocols:
            if not device.address:
                raise ValueError("Tapo device missing IP address")
            target_state = not bool(device.metadata.get("is_on", False))
            try:
                result = self.tapo.toggle(device.address, target_state)
            except NotImplementedError as exc:
                raise ValueError(str(exc)) from exc
            device.status = "online" if result else "offline"
            device.metadata.update({"is_on": result, "last_toggle": now})
        else:
            raise ValueError("Unsupported protocol for toggle operation")

        device.last_seen = now
        await self._persist_devices()
        return device

    async def ping_device(self, device_id: str) -> None:
        # Support looking up tapo devices whose ids are stored as 'tapo-<id>' or regular devices
        device = self.devices.get(device_id)
        now = datetime.utcnow().isoformat()

        # If not a managed device but prefixed tapo, try to construct a lightweight Device from tapo store
        if not device and device_id.startswith("tapo-"):
            tid = device_id[5:]
            td = self.tapo.get_device(tid)
            if td:
                device = Device(
                    id=device_id,
                    name=td.name,
                    type=td.type,
                    room="Tapo",
                    protocols=["tapo"],
                    integrations=["tapo"],
                    status="offline",
                    last_seen="Never",
                    firmware="Unknown",
                    address=td.ip,
                    metadata=td.metadata,
                )
            else:
                raise ValueError("Unknown device")

        success = False
        if "bluetooth" in device.protocols and device.address:
            success = await self.bluetooth.ping(device.address)
        elif "homekit" in device.protocols:
            pairing_id = device.metadata.get("pairing_id")
            aid = device.metadata.get("aid")
            iid = device.metadata.get("iid")
            if pairing_id is None or aid is None or iid is None:
                raise ValueError("HomeKit device missing pairing metadata")
            success = await self.homekit.ping(pairing_id, aid=int(aid), iid=int(iid))
            device.metadata["is_on"] = success
        elif "tapo" in device.protocols and device.address:
            # lightweight HTTP probe via tapo controller
            success = self.tapo.ping(device.address)
            device.metadata["is_on"] = success
        else:
            raise ValueError("Unsupported protocol for ping operation")

        device.last_seen = now
        device.status = "online" if success else "offline"
        await self._persist_devices()

    async def scan(self) -> List[Dict[str, object]]:
        discovered: List[Device] = []
        now = datetime.utcnow().isoformat()

        ble_devices = await self.bluetooth.scan(timeout=SCAN_TIMEOUT)
        for entry in ble_devices:
            device_id = entry.identifier
            existing = self.devices.get(device_id)
            if existing:
                existing.address = entry.address
                existing.metadata["rssi"] = entry.rssi
                existing.metadata["last_scan"] = now
                continue
            device = Device(
                id=device_id,
                name=entry.name,
                type="Display",
                room="Unassigned",
                protocols=["bluetooth"],
                integrations=[],
                status="offline",
                last_seen=now,
                firmware="Unknown",
                address=entry.address,
                metadata={"rssi": entry.rssi, "last_scan": now},
            )
            self.devices[device_id] = device
            discovered.append(device)

        homekit_new = await self._refresh_homekit_cache()
        discovered.extend(homekit_new)

        await self._persist_devices()
        return [device.to_dict() for device in discovered]

    async def pair_bluetooth_device(self, payload: Dict[str, Any]) -> Device:
        address_raw = str(payload.get("address") or "").strip()
        if not address_raw:
            raise ValueError("Bluetooth address required for pairing")

        try:
            address = self._normalize_bt_address(address_raw)
        except ValueError as error:
            raise ValueError(str(error)) from error
        device_id = str(payload.get("device_id") or "").strip()
        if not device_id:
            device_id = f"ble-{address.lower().replace(':', '')}"

        name = str(payload.get("name") or address)
        room = str(payload.get("room") or "Unassigned")
        device_type = str(payload.get("type") or "Display")
        commands_payload = payload.get("commands") or []

        normalized_commands = self._normalize_command_list(commands_payload)

        existing = self.devices.get(device_id)
        if existing:
            device = existing
        else:
            device = Device(
                id=device_id,
                name=name,
                type=device_type,
                room=room,
                protocols=["bluetooth"],
                integrations=["scene"],
                status="offline",
                last_seen="Never",
                firmware="Unknown",
                address=address,
                metadata={},
            )
            self.devices[device_id] = device

        device.name = name
        device.room = room
        device.type = device_type
        device.address = address
        device.protocols = sorted(set(device.protocols + ["bluetooth"]))
        device.integrations = sorted(set(device.integrations + ["scene"]))

        metadata = device.metadata or {}
        if not metadata.get("paired") or not metadata.get("trusted"):
            try:
                await self.bluetooth.pair_and_trust(address)
                timestamp = datetime.utcnow().isoformat()
                metadata["paired"] = True
                metadata["paired_at"] = timestamp
                metadata["trusted"] = True
                metadata["trusted_at"] = timestamp
                metadata["pair_agent"] = "NoInputNoOutput"
            except Exception as error:
                raise ValueError(f"Pairing failed: {error}") from error

        metadata.update(
            {
                "paired": True,
                "paired_at": metadata.get("paired_at", datetime.utcnow().isoformat()),
                "trusted": metadata.get("trusted", False),
                "trusted_at": metadata.get("trusted_at"),
                "ble_commands": normalized_commands,
            }
        )
        device.metadata = metadata

        await self._persist_devices()
        return device

    def start_pairing_job(self, payload: Dict[str, Any]) -> str:
        """Start a non-blocking pairing job and return a job id.

        The background task will update self._pairing_jobs[job_id] with status
        and result so callers can poll the status endpoint.
        """
        import uuid

        job_id = str(uuid.uuid4())
        self._pairing_jobs[job_id] = {
            "status": "pending",
            "device_id": None,
            "error": None,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
        }

        async def _job():
            self._pairing_jobs[job_id]["status"] = "in-progress"
            try:
                device = await self.pair_bluetooth_device(payload)
                self._pairing_jobs[job_id]["status"] = "success"
                self._pairing_jobs[job_id]["device_id"] = device.id
            except Exception as exc:  # pragma: no cover - runtime dependent
                import traceback

                tb = traceback.format_exc()
                self._pairing_jobs[job_id]["status"] = "failed"
                self._pairing_jobs[job_id]["error"] = str(exc)
                self._pairing_jobs[job_id]["traceback"] = tb
                # Log full traceback for remote diagnostics
                logger = logging.getLogger(__name__)
                logger.exception('Pairing job %s failed: %s', job_id, exc)
            finally:
                self._pairing_jobs[job_id]["finished_at"] = datetime.utcnow().isoformat()

        # schedule background task
        try:
            asyncio.create_task(_job())
        except RuntimeError:
            # If no running loop (e.g., during sync tests), run in background thread
            asyncio.get_event_loop().create_task(_job())

        return job_id

    def get_pairing_job(self, job_id: str) -> Optional[Dict[str, object]]:
        return self._pairing_jobs.get(job_id)

    async def send_command(self, device_id: str, command_id: str) -> Device:
        device = self.devices.get(device_id)
        if not device:
            raise ValueError("Unknown device")
        if "bluetooth" not in device.protocols:
            raise ValueError("Device does not support Bluetooth commands")
        if not device.address:
            raise ValueError("Bluetooth device missing address")

        command_map = self._ble_command_map(device)
        command = command_map.get(command_id)
        if not command:
            raise ValueError(f"Command '{command_id}' not configured for {device.name}")

        await self._perform_ble_command(device, command)

        now = datetime.utcnow().isoformat()
        metadata = device.metadata or {}
        metadata["last_command"] = {"id": command_id, "at": now}
        command_id_lower = command_id.lower()
        if command_id_lower == "power_off":
            metadata["is_on"] = False
            device.status = "offline"
        elif command_id_lower == "power_on":
            metadata["is_on"] = True
            device.status = "online"
        elif command_id_lower == "power_toggle":
            current = bool(metadata.get("is_on", device.status == "online"))
            metadata["is_on"] = not current
            device.status = "online" if metadata["is_on"] else "offline"

        device.metadata = metadata
        device.last_seen = now
        if device.status not in {"online", "offline"}:
            device.status = "online"

        await self._persist_devices()
        return device

    async def update_settings(self, settings: Dict[str, object]) -> Dict[str, object]:
        self._settings_path.write_text(json.dumps(settings, indent=2))
        return settings

    async def load_settings(self) -> Dict[str, object]:
        data = json.loads(self._settings_path.read_text())
        return data

    async def append_update_history(self, entry: Dict[str, str]) -> List[Dict[str, str]]:
        history = await self.load_update_history()
        history.append(entry)
        self._update_history_path.write_text(json.dumps(history, indent=2))
        return history

    async def load_update_history(self) -> List[Dict[str, str]]:
        return json.loads(self._update_history_path.read_text())

    async def stats(self) -> Dict[str, int]:
        await self._refresh_homekit_cache()
        devices = list(self.devices.values())
        total = len(devices)
        online = len([d for d in devices if d.status == "online"])
        homekit = len([d for d in devices if "homekit" in d.protocols])
        legacy = len([d for d in devices if "ir" in d.protocols])
        return {
            "total": total,
            "online": online,
            "homekit": homekit,
            "legacy": legacy,
        }

    def _normalize_bt_address(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Bluetooth address required")

        cleaned = cleaned.replace("-", ":").replace(".", ":").replace("/", ":")
        lowered = cleaned.lower()
        if lowered.startswith("dev_"):
            cleaned = cleaned[4:]
        cleaned = cleaned.replace("_", ":")
        cleaned = re.sub(r"\s+", "", cleaned)

        hex_only = re.sub(r"[^0-9A-Fa-f]", "", cleaned)
        if len(hex_only) != 12:
            raise ValueError("Bluetooth address must be 12 hex characters (e.g. AA:BB:CC:DD:EE:FF)")

        formatted = ":".join(hex_only[i : i + 2] for i in range(0, 12, 2)).upper()
        return formatted

    def _normalize_command_list(self, commands: Any) -> List[Dict[str, Any]]:
        normalized: Dict[str, Dict[str, Any]] = {}
        if not isinstance(commands, list):
            return []
        for raw in commands:
            if not isinstance(raw, dict):
                continue
            try:
                spec = self._normalize_command_spec(raw)
            except ValueError:
                continue
            normalized[spec["id"]] = spec
        return list(normalized.values())

    def _normalize_command_spec(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        command_id = str(raw.get("id") or "").strip()
        if not command_id:
            raise ValueError("Command id missing")
        characteristic = str(raw.get("characteristic") or "").strip().lower()
        if not characteristic:
            raise ValueError("Characteristic missing for command")
        payload_hex_raw = raw.get("payload_hex")
        payload_ascii_raw = raw.get("payload_ascii")
        payload_hex = str(payload_hex_raw).strip() if payload_hex_raw else ""
        if payload_ascii_raw is not None and not isinstance(payload_ascii_raw, str):
            raise ValueError("payload_ascii must be a string")
        if payload_hex:
            self._decode_payload_hex(payload_hex)
        label = str(raw.get("label") or command_id.replace("_", " ").title()).strip()
        spec: Dict[str, Any] = {
            "id": command_id,
            "label": label,
            "characteristic": characteristic,
            "with_response": bool(raw.get("with_response", False)),
        }
        if payload_hex:
            spec["payload_hex"] = payload_hex
        elif isinstance(payload_ascii_raw, str) and payload_ascii_raw:
            spec["payload_ascii"] = payload_ascii_raw
        else:
            spec["payload_hex"] = ""
        return spec

    def _ble_command_map(self, device: Device) -> Dict[str, Dict[str, Any]]:
        metadata = device.metadata or {}
        commands = metadata.get("ble_commands")
        result: Dict[str, Dict[str, Any]] = {}
        if isinstance(commands, list):
            for entry in commands:
                if not isinstance(entry, dict):
                    continue
                command_id = str(entry.get("id") or "").strip()
                if not command_id:
                    continue
                result[command_id] = entry

        # Support a mapping of logical actions -> command ids (written by the mobile UI)
        # metadata['ble_commands_map'] example: {"up": "cmd_up_id", "vol_up": "cmd_vol_plus"}
        mapping = metadata.get("ble_commands_map")
        if isinstance(mapping, dict):
            for logical_action, cmdid in mapping.items():
                try:
                    cid = str(cmdid or "").strip()
                except Exception:
                    continue
                if not cid:
                    continue
                # If the underlying command exists in result (from ble_commands), map logical_action -> that spec
                if cid in result:
                    result[logical_action] = result[cid]
        return result

    async def _perform_ble_command(self, device: Device, command: Dict[str, Any]) -> None:
        if not device.address:
            raise ValueError("Bluetooth device missing address")
        characteristic = str(command.get("characteristic") or "").strip()
        if not characteristic:
            raise ValueError("Command missing characteristic")

        payload_hex = str(command.get("payload_hex") or "").strip()
        payload_ascii = command.get("payload_ascii")
        with_response = bool(command.get("with_response", False))

        if payload_hex:
            payload = self._decode_payload_hex(payload_hex)
        elif isinstance(payload_ascii, str) and payload_ascii:
            payload = payload_ascii.encode("utf-8")
        else:
            payload = b""

        await self.bluetooth.send_command(
            device.address,
            characteristic=characteristic,
            payload=payload,
            with_response=with_response,
        )

    def _decode_payload_hex(self, payload_hex: str) -> bytes:
        cleaned = payload_hex.replace("0x", "")
        cleaned = "".join(ch for ch in cleaned if ch not in {" ", "-", ":", ",", "\n", "\t"})
        if len(cleaned) % 2 != 0:
            raise ValueError("Hex payload must have an even number of characters")
        try:
            return bytes.fromhex(cleaned)
        except ValueError as error:
            raise ValueError("Invalid hex payload") from error

    async def _toggle_with_commands(
        self,
        device: Device,
        commands: Dict[str, Dict[str, Any]],
        target_state: bool,
        timestamp: str,
    ) -> bool:
        metadata = device.metadata or {}
        if target_state and "power_on" in commands:
            await self._perform_ble_command(device, commands["power_on"])
            metadata["is_on"] = True
            device.status = "online"
            metadata["last_toggle"] = timestamp
            device.metadata = metadata
            return True
        if not target_state and "power_off" in commands:
            await self._perform_ble_command(device, commands["power_off"])
            metadata["is_on"] = False
            device.status = "offline"
            metadata["last_toggle"] = timestamp
            device.metadata = metadata
            return False
        if "power_toggle" in commands:
            await self._perform_ble_command(device, commands["power_toggle"])
            current = bool(metadata.get("is_on", device.status == "online"))
            metadata["is_on"] = not current
            device.status = "online" if metadata["is_on"] else "offline"
            metadata["last_toggle"] = timestamp
            device.metadata = metadata
            return metadata["is_on"]
        raise ValueError("Bluetooth device missing power command mapping")
