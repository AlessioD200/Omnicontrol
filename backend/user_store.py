from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

STORE_FILE = Path("state/users.json")
STORE_FILE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class User:
    id: str
    email: Optional[str]
    token: str
    linked_hub: Optional[str] = None


def _load_store() -> Dict[str, Dict]:
    if not STORE_FILE.exists():
        return {}
    try:
        return json.loads(STORE_FILE.read_text())
    except Exception:
        return {}


def _save_store(store: Dict[str, Dict]) -> None:
    STORE_FILE.write_text(json.dumps(store, indent=2))


def create_or_update_user(user_id: str, token: str, email: Optional[str] = None) -> User:
    store = _load_store()
    store[user_id] = {"id": user_id, "email": email, "token": token, "linked_hub": None}
    _save_store(store)
    return User(id=user_id, email=email, token=token, linked_hub=None)


def link_hub_for_user(user_id: str, hub_url: str) -> Optional[User]:
    store = _load_store()
    entry = store.get(user_id)
    if not entry:
        return None
    entry["linked_hub"] = hub_url
    _save_store(store)
    return User(**entry)


def find_user_by_token(token: str) -> Optional[User]:
    store = _load_store()
    for entry in store.values():
        if entry.get("token") == token:
            return User(**entry)
    return None
