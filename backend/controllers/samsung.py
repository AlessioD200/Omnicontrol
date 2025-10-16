from __future__ import annotations

import asyncio
import base64
import json
import ssl
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import websockets


@dataclass
class SamsungRemoteResult:
    token: Optional[str]
    messages: List[Dict[str, Any]]
    error: Optional[str] = None


class SamsungRemoteController:
    """Minimal Samsung SmartView remote helper.

    Each call establishes a short-lived TLS websocket, grabs any token updates,
    sends the requested key presses, and returns handshake metadata. The
    controller intentionally disables certificate validation because Samsung
    ships a self-signed SmartViewSDK CA on these devices.
    """

    def __init__(self) -> None:
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE
        self._locks: Dict[str, asyncio.Lock] = {}

    async def send_key(
        self,
        *,
        ip: str,
        client_id: str,
        name: str,
        key: str,
        token: Optional[str] = None,
        action: str = "Click",
        option: str = "false",
        remote_type: str = "SendRemoteKey",
        repeat: int = 1,
        repeat_delay: float = 0.0,
    ) -> SamsungRemoteResult:
        """Send a SmartView remote key press.

        Parameters mirror Samsung's JSON schema;  repeat_delay is expressed in
        seconds and only applies when repeat > 1.
        """

        lock = self._locks.setdefault(ip, asyncio.Lock())
        async with lock:
            url = self._build_url(ip, client_id, name, token)
            messages: List[Dict[str, Any]] = []
            extracted_token: Optional[str] = None
            error_message: Optional[str] = None

            try:
                async with websockets.connect(
                    url,
                    ssl=self._ssl,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=1.0,
                    max_size=4 * 1024 * 1024,
                ) as websocket:
                    await self._send_connect(websocket, client_id, name, token)
                    handshake_msgs = await self._drain_until_idle(websocket, limit=4)
                    messages.extend(handshake_msgs)
                    extracted_token = extracted_token or self._extract_token(handshake_msgs)
                    error_message = self._first_error(handshake_msgs)

                    if error_message and "unauthorized" in error_message.lower():
                        return SamsungRemoteResult(token=extracted_token, messages=messages, error=error_message)

                    payload = self._build_key_payload(key, action, option, remote_type)
                    total = max(repeat, 1)
                    for index in range(total):
                        await websocket.send(payload)
                        if repeat_delay > 0 and index < total - 1:
                            await asyncio.sleep(repeat_delay)

                    ack_msgs = await self._drain_until_idle(websocket, limit=4)
                    messages.extend(ack_msgs)
                    extracted_token = extracted_token or self._extract_token(ack_msgs)
                    error_message = error_message or self._first_error(ack_msgs)

                    try:
                        await websocket.send(
                            json.dumps(
                                {
                                    "method": "ms.channel.disconnect",
                                    "params": {"client_id": client_id},
                                }
                            )
                        )
                    except Exception:
                        pass
            except Exception as exc:
                return SamsungRemoteResult(token=extracted_token, messages=messages, error=str(exc))

            return SamsungRemoteResult(token=extracted_token, messages=messages, error=error_message)

    async def _send_connect(
        self,
        websocket: websockets.WebSocketClientProtocol,
        client_id: str,
        name: str,
        token: Optional[str],
    ) -> None:
        params: Dict[str, Any] = {
            "client_id": client_id,
            "name": self._encode_name(name),
            "appId": "omnicontrol",
            "user": "Omnicontrol",
            "type": "remote",
        }
        if token:
            params["token"] = token
        message = {"method": "ms.channel.connect", "params": params}
        await websocket.send(json.dumps(message))

    async def _drain_until_idle(
        self,
        websocket: websockets.WebSocketClientProtocol,
        *,
        timeout: float = 1.5,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        responses: List[Dict[str, Any]] = []
        for _ in range(limit):
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                break
            except websockets.ConnectionClosedOK:
                break
            except websockets.ConnectionClosedError:
                break
            parsed = self._maybe_parse(raw)
            if parsed is None:
                continue
            responses.append(parsed)
        return responses

    def _first_error(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        for entry in messages:
            if not isinstance(entry, dict):
                continue
            data = entry.get("data")
            if isinstance(data, dict):
                message = data.get("message") or data.get("status_message")
                if isinstance(message, str) and message:
                    status = str(data.get("status") or "").lower()
                    code = str(data.get("code") or "").lower()
                    if any(token in code for token in {"unauthorized", "forbidden", "denied"}):
                        return message
                    if any(token in message.lower() for token in {"denied", "unauthorized", "forbidden"}):
                        return message
        return None

    def _build_url(self, ip: str, client_id: str, name: str, token: Optional[str]) -> str:
        params = {
            "name": self._encode_name(name),
            "client_id": client_id,
        }
        if token:
            params["token"] = token
        query = urlencode(params)
        return f"wss://{ip}:8002/api/v2/channels/samsung.remote.control?{query}"

    def _encode_name(self, name: str) -> str:
        return base64.b64encode(name.encode("utf-8")).decode("ascii")

    def _extract_token(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        for entry in messages:
            if not isinstance(entry, dict):
                continue
            token = entry.get("token")
            if isinstance(token, (str, int)) and str(token):
                return str(token)
            data = entry.get("data")
            if isinstance(data, dict):
                token = data.get("token")
                if isinstance(token, (str, int)) and str(token):
                    return str(token)
        return None

    def _maybe_parse(self, payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = payload.decode("utf-8")
            except Exception:
                return None
        if isinstance(payload, str):
            payload = payload.strip()
            if not payload:
                return None
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                return parsed
        return None

    def _build_key_payload(
        self,
        key: str,
        action: str,
        option: str,
        remote_type: str,
    ) -> str:
        option_value: str
        if isinstance(option, bool):
            option_value = "true" if option else "false"
        else:
            option_value = str(option)
        payload = {
            "method": "ms.remote.control",
            "params": {
                "Cmd": action,
                "DataOfCmd": key,
                "Option": option_value,
                "TypeOfRemote": remote_type,
            },
        }
        return json.dumps(payload)


def generate_client_id() -> str:
    return str(uuid.uuid4())