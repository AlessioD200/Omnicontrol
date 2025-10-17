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
import logging
import os


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

    def __init__(self, *, verbose: bool = False) -> None:
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE
        self._locks: Dict[str, asyncio.Lock] = {}
        # Keep a cache of active websockets per ip so we can reuse a connection
        # and avoid prompting the user on the TV/monitor for each key press.
        self._sockets: Dict[str, websockets.WebSocketClientProtocol] = {}
        # Track whether we've completed the initial ms.channel.connect on a
        # given socket (so we don't re-send connect repeatedly).
        self._socket_connected: Dict[str, bool] = {}
        self._logger = logging.getLogger('controllers.samsung')
        self._verbose = bool(verbose)
        # If verbose, try to log to /var/log/omnicontrol/samsung.log when writable
        if self._verbose:
            try:
                logdir = '/var/log/omnicontrol'
                os.makedirs(logdir, exist_ok=True)
                fh = logging.FileHandler(os.path.join(logdir, 'samsung.log'))
                fh.setLevel(logging.DEBUG)
                self._logger.addHandler(fh)
            except Exception:
                pass

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
                # Reuse an existing open websocket for this IP when possible.
                websocket = self._sockets.get(ip)
                if websocket is None or websocket.closed:
                    websocket = await websockets.connect(
                        url,
                        ssl=self._ssl,
                        ping_interval=30,
                        ping_timeout=10,
                        close_timeout=1.0,
                        max_size=4 * 1024 * 1024,
                    )
                    self._sockets[ip] = websocket
                    # Mark that we haven't yet sent ms.channel.connect on this socket
                    self._socket_connected[ip] = False

                # If we haven't yet performed the channel connect on this socket,
                # do so now and drain initial handshake messages.
                if not self._socket_connected.get(ip, False):
                    await self._send_connect(websocket, client_id, name, token)
                    handshake_msgs = await self._drain_until_idle(websocket, limit=4)
                    if self._verbose:
                        try:
                            self._logger.debug('Handshake messages: %s', json.dumps(handshake_msgs))
                        except Exception:
                            self._logger.debug('Handshake messages: %r', handshake_msgs)
                    messages.extend(handshake_msgs)
                    extracted_token = extracted_token or self._extract_token(handshake_msgs)
                    error_message = self._first_error(handshake_msgs)
                    # If handshake returned an authorization error, don't proceed.
                    if error_message and "unauthorized" in error_message.lower():
                        return SamsungRemoteResult(token=extracted_token, messages=messages, error=error_message)
                    self._socket_connected[ip] = True

                # Build payload and send repeated keypresses on the same socket.
                payload = self._build_key_payload(key, action, option, remote_type)
                total = max(repeat, 1)
                for index in range(total):
                    await websocket.send(payload)
                    if repeat_delay > 0 and index < total - 1:
                        await asyncio.sleep(repeat_delay)

                # Drain for any ack messages produced by the key press(es).
                ack_msgs = await self._drain_until_idle(websocket, limit=4)
                if self._verbose:
                    try:
                        self._logger.debug('Ack messages: %s', json.dumps(ack_msgs))
                    except Exception:
                        self._logger.debug('Ack messages: %r', ack_msgs)
                messages.extend(ack_msgs)
                extracted_token = extracted_token or self._extract_token(ack_msgs)
                error_message = error_message or self._first_error(ack_msgs)
            except Exception as exc:
                # If we hit an exception with the reused socket, close and remove it
                try:
                    ws = self._sockets.get(ip)
                    if ws is not None and not ws.closed:
                        await ws.close()
                except Exception:
                    pass
                self._sockets.pop(ip, None)
                self._socket_connected.pop(ip, None)
                if self._verbose:
                    self._logger.exception('send_key failed: %s', exc)
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
                # Direct token field
                token = data.get("token")
                if isinstance(token, (str, int)) and str(token):
                    return str(token)
                # Some Samsung devices include client identifiers inside the
                # ms.channel.connect payload: data.clients[].attributes.client_id
                clients = data.get("clients")
                if isinstance(clients, list):
                    for client in clients:
                        if not isinstance(client, dict):
                            continue
                        attrs = client.get("attributes")
                        if isinstance(attrs, dict):
                            cid = attrs.get("client_id") or attrs.get("clientId")
                            if isinstance(cid, (str, int)) and str(cid):
                                return str(cid)
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