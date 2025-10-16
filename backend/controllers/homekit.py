from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from aiohomekit import Controller
from aiohomekit.exceptions import AccessoryNotFoundError
from aiohomekit.model.characteristics import CharacteristicsTypes
from aiohomekit.model.services import ServicesTypes

try:  # aiohomekit >= 2.8
    from aiohomekit.storage import HomeKitStore  # type: ignore
except ImportError:  # aiohomekit < 2.8 fallback
    HomeKitStore = None  # type: ignore


@dataclass
class HomeKitDevice:
    identifier: str
    name: str
    room: str
    pairing_id: str
    aid: int
    iid: int
    is_on: bool

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.identifier,
            "name": self.name,
            "room": self.room,
            "pairing_id": self.pairing_id,
            "aid": self.aid,
            "iid": self.iid,
            "is_on": self.is_on,
        }


TOGGLE_SERVICES = {
    ServicesTypes.LIGHTBULB,
    ServicesTypes.SWITCH,
    ServicesTypes.OUTLET,
}


class HomeKitController:
    """Handles paired HomeKit accessories via aiohomekit."""

    def __init__(self, store_path: Path) -> None:
        self._store_path = Path(store_path)
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store = HomeKitStore(str(self._store_path)) if HomeKitStore else None
        self._controller = Controller(self._store) if self._store else Controller()
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def startup(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            if self._store:
                await self._store.async_load()
            elif self._store_path.exists():
                try:
                    data = json.loads(self._store_path.read_text())
                    self._controller.load_data(data)
                except Exception:
                    pass
            self._initialized = True

    async def list_devices(self) -> List[HomeKitDevice]:
        await self._ensure_ready()
        devices: List[HomeKitDevice] = []
        for pairing_id, pairing in self._controller.pairings.items():
            await pairing.list_accessories_and_characteristics()
            for accessory in pairing.accessories:
                room = getattr(accessory, "room", None) or "HomeKit"
                name = getattr(accessory, "display_name", None) or getattr(accessory, "name", None)
                for service in accessory.services:
                    if service.type not in TOGGLE_SERVICES:
                        continue
                    if CharacteristicsTypes.ON not in service.characteristics:
                        continue
                    characteristic = service.characteristics[CharacteristicsTypes.ON]
                    identifier = f"hk-{pairing_id}-{characteristic.aid}-{characteristic.iid}"
                    devices.append(
                        HomeKitDevice(
                            identifier=identifier,
                            name=name or service.display_name or identifier,
                            room=room,
                            pairing_id=pairing_id,
                            aid=characteristic.aid,
                            iid=characteristic.iid,
                            is_on=bool(characteristic.value),
                        )
                    )
        return devices

    async def toggle(self, pairing_id: str, *, aid: int, iid: int, turn_on: Optional[bool] = None) -> bool:
        await self._ensure_ready()
        pairing = self._controller.pairings.get(pairing_id)
        if not pairing:
            raise AccessoryNotFoundError(f"Unknown pairing {pairing_id}")
        await pairing.list_accessories_and_characteristics()
        values = await pairing.get_characteristics([(aid, iid)])
        current = bool(values[(aid, iid)])
        target = not current if turn_on is None else turn_on
        await pairing.put_characteristics({(aid, iid): int(target)})
        if self._store:
            await self._store.async_save()
        else:
            try:
                self._store_path.write_text(json.dumps(self._controller.dump()))
            except Exception:
                pass
        return target

    async def ping(self, pairing_id: str, *, aid: int, iid: int) -> bool:
        await self._ensure_ready()
        pairing = self._controller.pairings.get(pairing_id)
        if not pairing:
            raise AccessoryNotFoundError(f"Unknown pairing {pairing_id}")
        try:
            values = await pairing.get_characteristics([(aid, iid)])
        except Exception:
            return False
        return bool(values[(aid, iid)])

    async def _ensure_ready(self) -> None:
        if not self._initialized:
            await self.startup()
