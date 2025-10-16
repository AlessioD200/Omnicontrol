"""Minimal RFCOMM helper for classic Bluetooth command delivery."""

from __future__ import annotations

import socket
import time


class RFCOMMError(RuntimeError):
    """Raised when RFCOMM operations fail."""


def _ensure_support() -> None:
    if not hasattr(socket, "AF_BLUETOOTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
        raise RFCOMMError(
            "Python bluetooth socket support is unavailable; ensure BlueZ headers are present"
        )


def send_command(
    address: str,
    channel: int,
    payload: bytes,
    *,
    connect_timeout: float = 5.0,
    response_bytes: int = 0,
    response_timeout: float = 1.0,
    wait_time: float = 0.0,
) -> bytes:
    """Send a payload over RFCOMM and optionally read a response."""
    if channel <= 0 or channel > 30:
        raise RFCOMMError("RFCOMM channel must be between 1 and 30")
    _ensure_support()

    timeout = max(0.2, float(connect_timeout))
    recv_timeout = max(0.1, float(response_timeout))
    expect = max(0, int(response_bytes))

    try:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    except OSError as exc:  # pragma: no cover - depends on kernel support
        raise RFCOMMError(f"Failed to allocate RFCOMM socket: {exc}") from exc

    try:
        sock.settimeout(timeout)
        sock.connect((address, channel))
        if wait_time > 0:
            time.sleep(min(wait_time, 2.0))
        if payload:
            sock.sendall(payload)
        if expect <= 0:
            return b""
        sock.settimeout(recv_timeout)
        chunks = b""
        while len(chunks) < expect:
            try:
                chunk = sock.recv(expect - len(chunks))
            except OSError as exc:
                raise RFCOMMError(f"RFCOMM read failed: {exc}") from exc
            if not chunk:
                break
            chunks += chunk
        return chunks
    except OSError as exc:
        raise RFCOMMError(f"RFCOMM exchange failed: {exc}") from exc
    finally:
        try:
            sock.close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass