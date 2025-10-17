from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from controllers import (
    BluetoothController,
    HomeKitController,
    SamsungRemoteController,
    TapoController,
    generate_client_id,
)
import classic_rfcomm
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
    capabilities: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["protocols"] = sorted(set(self.protocols))
        payload["integrations"] = sorted(set(self.integrations))
        if payload.get("address") is None:
            payload.pop("address", None)
        if not payload.get("metadata"):
            payload["metadata"] = {}
        if not payload.get("capabilities"):
            payload["capabilities"] = {}
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
            capabilities=entry.get("capabilities", {}) or {},
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
        self.samsung = SamsungRemoteController(verbose=bool(os.getenv('OMNICONTROL_SAMSUNG_VERBOSE', '')))
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
            command_map = self._command_map(device)
            power_commands = {key: command_map[key] for key in command_map if key.startswith("power_")}
            if power_commands:
                result = await self._toggle_with_commands(
                    device,
                    command_map,
                    target_state,
                    now,
                )
            else:
                result = await self.bluetooth.toggle_power(
                    device.address,
                    characteristic=characteristic,
                    turn_on=target_state,
                )
                metadata = device.metadata or {}
                metadata["last_toggle"] = now
                device.metadata = metadata
            device.status = "online" if result else "offline"
        elif any(proto in device.protocols for proto in {"samsung", "smartview"}):
            target_state = device.status != "online"
            command_map = self._command_map(device)
            samsung_commands = {
                key: value
                for key, value in command_map.items()
                if key.startswith("power_") and str(value.get("transport") or "").lower() == "samsung"
            }
            if samsung_commands:
                result_state = await self._toggle_with_commands(device, command_map, target_state, now)
                device.status = "online" if result_state else "offline"
            else:
                raise ValueError("Samsung device missing power command mapping")
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

        classic_caps = await asyncio.to_thread(self.bluetooth.inspect_classic_capabilities, address)
        if classic_caps:
            metadata["classic_capabilities"] = json.loads(json.dumps(classic_caps))
            classic_profiles = set(classic_caps.get("profiles", []))
            device.capabilities.setdefault("classic", {}).update(classic_caps)
            if classic_profiles:
                media_caps = device.capabilities.setdefault("media", {})
                media_caps["avrcp"] = bool({"avrcp_controller", "avrcp_target"} & classic_profiles)
                media_caps["audio_sink"] = "audio_sink" in classic_profiles
                media_caps["handsfree"] = "handsfree_gateway" in classic_profiles or "headset_gateway" in classic_profiles

        ble_commands = [cmd for cmd in normalized_commands if (cmd.get("transport") or "ble").lower() != "rfcomm"]
        classic_commands = [cmd for cmd in normalized_commands if (cmd.get("transport") or "ble").lower() == "rfcomm"]
        if ble_commands:
            metadata["ble_commands"] = ble_commands
        elif "ble_commands" not in metadata:
            metadata["ble_commands"] = []
        if classic_commands:
            metadata["classic_commands"] = classic_commands

        metadata.update(
            {
                "paired": True,
                "paired_at": metadata.get("paired_at", datetime.utcnow().isoformat()),
                "trusted": metadata.get("trusted", False),
                "trusted_at": metadata.get("trusted_at"),
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

        command_map = self._command_map(device)
        command = command_map.get(command_id)
        if not command:
            raise ValueError(f"Command '{command_id}' not configured for {device.name}")

        transport = str(command.get("transport") or "ble").lower()
        if transport in {"ble", "rfcomm"}:
            if "bluetooth" not in device.protocols:
                raise ValueError("Device does not support Bluetooth commands")
            if not device.address:
                raise ValueError("Bluetooth device missing address")
        elif transport == "samsung":
            # Allow Samsung commands if device protocols include samsung/smartview
            # or if device metadata contains pairing info (token/client_id/ip)
            has_proto = any(proto in device.protocols for proto in {"samsung", "smartview"})
            has_meta = bool(device.metadata and any(k in device.metadata for k in ("samsung_token", "samsung_client_id", "smartview_token", "samsung_ip")))
            if not (has_proto or has_meta):
                raise ValueError("Device does not support Samsung SmartView commands")
        else:
            raise ValueError(f"Unsupported command transport '{transport}'")

        response_payload = await self._execute_command(device, command)

        now = datetime.utcnow().isoformat()
        metadata = device.metadata or {}
        last_entry = {"id": command_id, "at": now, "transport": transport}
        if response_payload:
            last_entry["response_len"] = len(response_payload)
            if transport == "samsung":
                try:
                    last_entry["response_json"] = json.loads(response_payload.decode("utf-8"))
                except Exception:
                    last_entry["response_hex"] = response_payload.hex()
            else:
                last_entry["response_hex"] = response_payload.hex()
        metadata["last_command"] = last_entry
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

    async def execute_inline_command(self, device_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        device = self.devices.get(device_id)
        if not device:
            raise ValueError("Unknown device")

        inline_spec = dict(payload)
        inline_spec["id"] = inline_spec.get("id") or "__inline__"
        try:
            normalized = self._normalize_command_spec(inline_spec)
        except ValueError as exc:
            raise ValueError(f"Invalid command specification: {exc}") from exc

        transport = str(normalized.get("transport") or "ble").lower()
        if transport in {"ble", "rfcomm"}:
            if "bluetooth" not in device.protocols:
                raise ValueError("Device does not support Bluetooth commands")
            if not device.address:
                raise ValueError("Bluetooth device missing address")
        elif transport == "samsung":
            if not any(proto in device.protocols for proto in {"samsung", "smartview"}):
                raise ValueError("Device does not support Samsung SmartView commands")
        else:
            raise ValueError(f"Unsupported command transport '{transport}'")

        payload_len = 0
        if normalized.get("payload_hex"):
            payload_len = len(self._decode_payload_hex(normalized.get("payload_hex", "")))
        elif isinstance(normalized.get("payload_ascii"), str) and normalized.get("payload_ascii"):
            payload_len = len(normalized["payload_ascii"].encode("utf-8"))

        response_payload = await self._execute_command(device, normalized)

        result: Dict[str, Any] = {
            "device": device_id,
            "transport": transport,
            "bytes_sent": payload_len,
        }
        if transport == "rfcomm":
            if normalized.get("rfcomm_channel") is not None:
                result["rfcomm_channel"] = normalized["rfcomm_channel"]
            if normalized.get("service_uuid"):
                result["service_uuid"] = normalized["service_uuid"]
            if normalized.get("service_name"):
                result["service_name"] = normalized["service_name"]
            if payload_len:
                result["payload_hex"] = normalized.get("payload_hex") or normalized.get("payload_ascii", "").encode("utf-8").hex()
            if normalized.get("response_bytes") is not None:
                result["response_expected"] = normalized.get("response_bytes")
        if response_payload:
            result["response_len"] = len(response_payload)
            if transport == "samsung":
                try:
                    result["response_json"] = json.loads(response_payload.decode("utf-8"))
                except Exception:
                    result["response_hex"] = response_payload.hex()
            else:
                result["response_hex"] = response_payload.hex()
        return result

    async def pair_samsung_device(self, device_id: str, ip: str, name: Optional[str] = None, pin: Optional[str] = None) -> Dict[str, Any]:
        """Attempt to pair with a Samsung SmartView device.

        This will try to establish a SmartView websocket, send a harmless key to
        trigger token issuance, persist client_id/ip/token into device metadata
        and return the controller result.
        """
        device = self.devices.get(device_id)
        if not device:
            raise ValueError("Unknown device")

        metadata = device.metadata or {}
        ip_val = str(ip).strip()
        if not ip_val:
            raise ValueError("IP required")

        existing_client = metadata.get("samsung_client_id") or metadata.get("smartview_client_id")
        client_id = existing_client or generate_client_id()
        if not existing_client:
            metadata["samsung_client_id"] = client_id

        friendly_name = (name or metadata.get("samsung_remote_name") or device.name or "Omnicontrol")

        # persist ip immediately so subsequent operations can reference it
        metadata["samsung_ip"] = ip_val
        device.metadata = metadata
        await self._persist_devices()

        # Try to send a benign key press to obtain/refresh token
        try:
            result = await self.samsung.send_key(
                ip=ip_val,
                client_id=client_id,
                name=friendly_name,
                key="MENU",
                token=None,
                action="Click",
            )
        except Exception as exc:
            raise RuntimeError(f"Pairing attempt failed: {exc}") from exc

        updated = False
        if result.token:
            metadata["samsung_token"] = result.token
            updated = True
            # Mark device as paired/trusted when we obtained a token
            metadata["paired"] = True
            metadata["trusted"] = True
            device.status = "online"
            device.last_seen = datetime.utcnow().isoformat()
        if metadata != (device.metadata or {}):
            device.metadata = metadata
            updated = True
        if updated:
            await self._persist_devices()

        # If pairing succeeded (we have a token), ensure device protocols include 'samsung'
        if result.token:
            if 'samsung' not in device.protocols:
                device.protocols.append('samsung')
                await self._persist_devices()

        return {"token": result.token, "messages": result.messages, "error": result.error}

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
        transport = str(raw.get("transport") or raw.get("protocol") or "ble").strip().lower()
        if transport not in {"ble", "rfcomm", "samsung"}:
            raise ValueError("Unsupported command transport")
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
            "transport": transport,
        }
        if transport == "ble":
            characteristic = str(raw.get("characteristic") or "").strip().lower()
            if not characteristic:
                raise ValueError("Characteristic missing for BLE command")
            spec["characteristic"] = characteristic
            spec["with_response"] = bool(raw.get("with_response", False))
        elif transport == "rfcomm":
            channel_raw = raw.get("rfcomm_channel")
            channel_val: Optional[int] = None
            if channel_raw is not None and str(channel_raw).strip():
                try:
                    channel_val = int(str(channel_raw).strip())
                except (TypeError, ValueError) as exc:
                    raise ValueError("rfcomm_channel must be an integer") from exc
                if channel_val <= 0 or channel_val > 30:
                    raise ValueError("rfcomm_channel must be between 1 and 30")
                spec["rfcomm_channel"] = channel_val
            service_uuid = str(raw.get("service_uuid") or "").strip().lower()
            if service_uuid:
                spec["service_uuid"] = service_uuid
            service_name = str(raw.get("service_name") or "").strip()
            if service_name:
                spec["service_name"] = service_name
            response_bytes = raw.get("response_bytes")
            if response_bytes is not None and str(response_bytes).strip() != "":
                try:
                    response_int = int(response_bytes)
                except (TypeError, ValueError) as exc:
                    raise ValueError("response_bytes must be an integer") from exc
                if response_int < 0:
                    raise ValueError("response_bytes must be >= 0")
                spec["response_bytes"] = response_int
            response_timeout = raw.get("response_timeout")
            if response_timeout is not None and str(response_timeout).strip() != "":
                try:
                    timeout_val = float(response_timeout)
                except (TypeError, ValueError) as exc:
                    raise ValueError("response_timeout must be numeric") from exc
                if timeout_val < 0:
                    raise ValueError("response_timeout must be >= 0")
                spec["response_timeout"] = timeout_val
            wait_ms = raw.get("wait_ms")
            if wait_ms is not None and str(wait_ms).strip() != "":
                try:
                    wait_int = int(wait_ms)
                except (TypeError, ValueError) as exc:
                    raise ValueError("wait_ms must be an integer") from exc
                if wait_int < 0:
                    raise ValueError("wait_ms must be >= 0")
                spec["wait_ms"] = wait_int
            if "rfcomm_channel" not in spec and "service_uuid" not in spec and "service_name" not in spec:
                raise ValueError("RFCOMM command requires rfcomm_channel, service_uuid, or service_name")
        else:  # samsung remote
            key_code = str(
                raw.get("key")
                or raw.get("key_code")
                or raw.get("data_of_cmd")
                or raw.get("data")
                or ""
            ).strip().upper()
            if not key_code:
                raise ValueError("Samsung command missing key")
            spec["key"] = key_code
            cmd_value = str(raw.get("cmd") or raw.get("action") or "Click").strip()
            if cmd_value:
                spec["cmd"] = cmd_value
            option_value = raw.get("option")
            if option_value is not None:
                spec["option"] = option_value
            remote_type = str(raw.get("remote_type") or raw.get("type_of_remote") or "SendRemoteKey").strip()
            if remote_type:
                spec["remote_type"] = remote_type
            repeat_value = raw.get("repeat")
            if repeat_value is not None and str(repeat_value).strip() != "":
                try:
                    repeat_int = int(repeat_value)
                except (TypeError, ValueError) as exc:
                    raise ValueError("repeat must be an integer") from exc
                if repeat_int <= 0:
                    raise ValueError("repeat must be >= 1")
                spec["repeat"] = repeat_int
            delay_ms_value = raw.get("repeat_delay_ms")
            delay_seconds_value = raw.get("repeat_delay")
            if delay_ms_value is not None and str(delay_ms_value).strip() != "":
                try:
                    delay_ms = int(float(delay_ms_value))
                except (TypeError, ValueError) as exc:
                    raise ValueError("repeat_delay_ms must be numeric") from exc
                if delay_ms < 0:
                    raise ValueError("repeat_delay_ms must be >= 0")
                spec["repeat_delay_ms"] = delay_ms
            elif delay_seconds_value is not None and str(delay_seconds_value).strip() != "":
                try:
                    delay_seconds = float(delay_seconds_value)
                except (TypeError, ValueError) as exc:
                    raise ValueError("repeat_delay must be numeric") from exc
                if delay_seconds < 0:
                    raise ValueError("repeat_delay must be >= 0")
                spec["repeat_delay_ms"] = int(round(delay_seconds * 1000))
            token_override = raw.get("token")
            if token_override:
                spec["token"] = str(token_override)
            ip_override = raw.get("ip") or raw.get("host")
            if ip_override:
                spec["ip"] = str(ip_override)
        if payload_hex:
            spec["payload_hex"] = payload_hex
        elif isinstance(payload_ascii_raw, str) and payload_ascii_raw:
            spec["payload_ascii"] = payload_ascii_raw
        else:
            spec["payload_hex"] = ""
        return spec

    def _command_map(self, device: Device) -> Dict[str, Dict[str, Any]]:
        metadata = device.metadata or {}
        result: Dict[str, Dict[str, Any]] = {}

        def _ingest(entries: Any) -> None:
            if not isinstance(entries, list):
                return
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                command_id = str(entry.get("id") or "").strip()
                if not command_id:
                    continue
                normalized = dict(entry)
                transport = str(normalized.get("transport") or "ble").lower()
                if transport not in {"ble", "rfcomm", "samsung"}:
                    transport = "ble"
                normalized["transport"] = transport
                if transport == "rfcomm" and normalized.get("rfcomm_channel") is not None:
                    try:
                        normalized["rfcomm_channel"] = int(normalized["rfcomm_channel"])
                    except (TypeError, ValueError):
                        normalized.pop("rfcomm_channel", None)
                result[command_id] = normalized

        _ingest(metadata.get("ble_commands"))
        _ingest(metadata.get("classic_commands"))
        _ingest(metadata.get("network_commands"))
        _ingest(metadata.get("samsung_commands"))

        def _apply_mapping(mapping: Any) -> None:
            if not isinstance(mapping, dict):
                return
            for logical_action, cmdid in mapping.items():
                try:
                    cid = str(cmdid or "").strip()
                except Exception:
                    continue
                if not cid:
                    continue
                if cid in result:
                    result[logical_action] = result[cid]

        _apply_mapping(metadata.get("ble_commands_map"))
        _apply_mapping(metadata.get("command_map"))

        return result

    async def _perform_ble_command(self, device: Device, command: Dict[str, Any]) -> bytes:
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
        return b""

    async def _perform_samsung_command(self, device: Device, command: Dict[str, Any]) -> bytes:
        metadata = device.metadata or {}

        raw_ip = command.get("ip") or command.get("host")
        ip = str(
            raw_ip
            or metadata.get("samsung_ip")
            or metadata.get("smartview_ip")
            or metadata.get("ip")
            or device.address
            or ""
        ).strip()
        if not ip:
            raise ValueError("Samsung device missing IP address")

        updated = False
        if raw_ip and metadata.get("samsung_ip") != ip:
            metadata["samsung_ip"] = ip
            updated = True

        existing_client_id = metadata.get("samsung_client_id") or metadata.get("smartview_client_id")
        client_id = str(command.get("client_id") or existing_client_id or "").strip()
        if not client_id:
            client_id = generate_client_id()
            metadata["samsung_client_id"] = client_id
            updated = True
        elif metadata.get("samsung_client_id") != client_id:
            metadata["samsung_client_id"] = client_id
            updated = True

        friendly_name = str(
            command.get("name")
            or metadata.get("samsung_remote_name")
            or device.name
            or "Omnicontrol"
        ).strip()
        if not friendly_name:
            friendly_name = "Omnicontrol"
        if command.get("name") and metadata.get("samsung_remote_name") != friendly_name:
            metadata["samsung_remote_name"] = friendly_name
            updated = True

        token_value = command.get("token") or metadata.get("samsung_token") or metadata.get("smartview_token")
        token = str(token_value).strip() if isinstance(token_value, (str, int)) else None
        if token == "":
            token = None

        key = str(command.get("key") or "").strip().upper()
        if not key:
            raise ValueError("Samsung command missing key")

        action = str(command.get("cmd") or command.get("action") or "Click").strip() or "Click"
        option_raw = command.get("option")
        remote_type = str(command.get("remote_type") or "SendRemoteKey").strip() or "SendRemoteKey"

        repeat_raw = command.get("repeat")
        try:
            repeat = int(repeat_raw) if repeat_raw is not None else 1
        except (TypeError, ValueError) as exc:
            raise ValueError("repeat must be an integer") from exc
        if repeat <= 0:
            repeat = 1

        delay_ms = command.get("repeat_delay_ms")
        delay_seconds = command.get("repeat_delay")
        if delay_ms is not None:
            try:
                repeat_delay = max(0.0, float(delay_ms) / 1000.0)
            except (TypeError, ValueError) as exc:
                raise ValueError("repeat_delay_ms must be numeric") from exc
        elif delay_seconds is not None:
            try:
                repeat_delay = max(0.0, float(delay_seconds))
            except (TypeError, ValueError) as exc:
                raise ValueError("repeat_delay must be numeric") from exc
        else:
            repeat_delay = 0.0

        result = await self.samsung.send_key(
            ip=ip,
            client_id=client_id,
            name=friendly_name,
            key=key,
            token=token,
            action=action,
            option=option_raw if option_raw is not None else "false",
            remote_type=remote_type,
            repeat=repeat,
            repeat_delay=repeat_delay,
        )

        if result.token:
            metadata["samsung_token"] = result.token
            updated = True
        elif result.error and "unauthorized" in result.error.lower():
            if metadata.pop("samsung_token", None) is not None:
                updated = True
        elif token and metadata.get("samsung_token") != token:
            metadata["samsung_token"] = token
            updated = True
        metadata["samsung_last_command"] = {
            "key": key,
            "timestamp": datetime.utcnow().isoformat(),
            "error": result.error,
        }
        device.metadata = metadata
        if updated:
            await self._persist_devices()

        payload = {
            "token": result.token,
            "messages": result.messages,
            "error": result.error,
        }
        return json.dumps(payload).encode("utf-8")

    def _decode_payload_hex(self, payload_hex: str) -> bytes:
        cleaned = payload_hex.replace("0x", "")
        cleaned = "".join(ch for ch in cleaned if ch not in {" ", "-", ":", ",", "\n", "\t"})
        if len(cleaned) % 2 != 0:
            raise ValueError("Hex payload must have an even number of characters")
        try:
            return bytes.fromhex(cleaned)
        except ValueError as error:
            raise ValueError("Invalid hex payload") from error

    async def _execute_command(self, device: Device, command: Dict[str, Any]) -> bytes:
        transport = str(command.get("transport") or "ble").lower()
        if transport == "samsung":
            return await self._perform_samsung_command(device, command)
        if transport == "rfcomm":
            return await self._perform_rfcomm_command(device, command)
        return await self._perform_ble_command(device, command)

    async def _perform_rfcomm_command(self, device: Device, command: Dict[str, Any]) -> bytes:
        if not device.address:
            raise ValueError("Bluetooth device missing address")
        channel = command.get("rfcomm_channel")
        service_uuid = str(command.get("service_uuid") or "").strip()
        service_name = str(command.get("service_name") or "").strip()

        channel_id: Optional[int] = None
        if channel is not None:
            try:
                channel_id = int(channel)
            except (TypeError, ValueError) as exc:
                raise ValueError("rfcomm_channel must be an integer") from exc
            if channel_id <= 0 or channel_id > 30:
                raise ValueError("rfcomm_channel must be between 1 and 30")

        lookup_target = service_uuid or service_name
        if channel_id is None and lookup_target:
            resolved = self._resolve_rfcomm_channel(device, lookup_target)
            if resolved is not None:
                channel_id = resolved
                command["rfcomm_channel"] = channel_id

        if channel_id is None:
            raise ValueError("RFCOMM command missing channel; supply rfcomm_channel or service reference")

        payload_hex = str(command.get("payload_hex") or "").strip()
        payload_ascii = command.get("payload_ascii")
        if payload_hex:
            payload = self._decode_payload_hex(payload_hex)
        elif isinstance(payload_ascii, str) and payload_ascii:
            payload = payload_ascii.encode("utf-8")
        else:
            payload = b""

        response_bytes = command.get("response_bytes")
        if response_bytes is None:
            expected_response = 0
        else:
            try:
                expected_response = int(response_bytes)
            except (TypeError, ValueError) as exc:
                raise ValueError("response_bytes must be an integer") from exc
            if expected_response < 0:
                raise ValueError("response_bytes must be >= 0")

        response_timeout = command.get("response_timeout")
        if response_timeout is None:
            response_timeout_val = 1.0
        else:
            try:
                response_timeout_val = float(response_timeout)
            except (TypeError, ValueError) as exc:
                raise ValueError("response_timeout must be numeric") from exc
            if response_timeout_val < 0:
                response_timeout_val = 0.0

        wait_ms = command.get("wait_ms")
        wait_seconds = 0.0
        if wait_ms is not None:
            try:
                wait_seconds = max(0.0, float(wait_ms) / 1000.0)
            except (TypeError, ValueError) as exc:
                raise ValueError("wait_ms must be numeric") from exc

        try:
            return await asyncio.to_thread(
                classic_rfcomm.send_command,
                device.address,
                channel_id,
                payload,
                connect_timeout=5.0,
                response_bytes=expected_response,
                response_timeout=response_timeout_val,
                wait_time=wait_seconds,
            )
        except classic_rfcomm.RFCOMMError as exc:
            raise RuntimeError(str(exc)) from exc

    def _resolve_rfcomm_channel(self, device: Device, identifier: str) -> Optional[int]:
        capabilities = device.capabilities or {}
        classic = capabilities.get("classic") or {}
        channels = classic.get("rfcomm_channels") or {}
        ident = identifier.strip().lower()
        if not ident:
            return None
        if ident in channels:
            try:
                return int(channels[ident])
            except (TypeError, ValueError):
                return None
        services = classic.get("services") or []
        for service in services:
            channel = service.get("rfcomm_channel")
            if channel is None:
                continue
            try:
                channel_int = int(channel)
            except (TypeError, ValueError):
                continue
            name = str(service.get("name") or "").strip().lower()
            if name and (ident == name or ident in name):
                return channel_int
            provider = str(service.get("provider") or "").strip().lower()
            if provider and (ident == provider or ident in provider):
                return channel_int
            for cls in service.get("class_ids") or []:
                label = str(cls.get("label") or "").strip().lower()
                uuid = str(cls.get("uuid") or "").strip().lower()
                if ident in {label, uuid}:
                    return channel_int
            for uuid in service.get("uuids") or []:
                uuid_lower = str(uuid or "").strip().lower()
                if ident == uuid_lower:
                    return channel_int
        return None

    async def _toggle_with_commands(
        self,
        device: Device,
        commands: Dict[str, Dict[str, Any]],
        target_state: bool,
        timestamp: str,
    ) -> bool:
        metadata = device.metadata or {}
        if target_state and "power_on" in commands:
            await self._execute_command(device, commands["power_on"])
            metadata["is_on"] = True
            device.status = "online"
            metadata["last_toggle"] = timestamp
            device.metadata = metadata
            return True
        if not target_state and "power_off" in commands:
            await self._execute_command(device, commands["power_off"])
            metadata["is_on"] = False
            device.status = "offline"
            metadata["last_toggle"] = timestamp
            device.metadata = metadata
            return False
        if "power_toggle" in commands:
            await self._execute_command(device, commands["power_toggle"])
            current = bool(metadata.get("is_on", device.status == "online"))
            metadata["is_on"] = not current
            device.status = "online" if metadata["is_on"] else "offline"
            metadata["last_toggle"] = timestamp
            device.metadata = metadata
            return metadata["is_on"]
        raise ValueError("Bluetooth device missing power command mapping")
