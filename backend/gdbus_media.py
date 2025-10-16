"""Helper to call BlueZ MediaPlayer/MediaControl methods via gdbus.

This wrapper keeps the implementation in one place so the backend can
trigger classic Bluetooth AVRCP commands without depending on dbus-next.
"""

import subprocess
import time
from typing import Optional


def _mac_to_path(mac: str) -> str:
    return "/org/bluez/hci0/dev_" + mac.replace(":", "_")


def _find_player_path(mac: str) -> Optional[str]:
    dev_path = _mac_to_path(mac)
    # Use ObjectManager.GetManagedObjects to find any object under the device
    # path that implements org.bluez.MediaPlayer1. This is more reliable than
    # introspect because some BlueZ stacks create empty player nodes or place
    # player objects elsewhere.
    try:
        cmd = [
            "gdbus",
            "call",
            "--system",
            "--dest",
            "org.bluez",
            "--object-path",
            "/",
            "--method",
            "org.freedesktop.DBus.ObjectManager.GetManagedObjects",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise RuntimeError("gdbus not found; install libglib2.0-bin")
    if res.returncode != 0:
        stderr = (res.stderr or "").strip()
        stdout = (res.stdout or "").strip()
        details = stderr or stdout or f"exit code {res.returncode}"
        raise RuntimeError(f"Failed to query BlueZ managed objects: {details}")

    out = res.stdout or ""
    # Look for any object path under the device path that mentions MediaPlayer1
    lines = out.splitlines()
    for line in lines:
        if dev_path in line and 'MediaPlayer1' in line:
            # Extract the object path between the leading "'" or space and the colon
            # The gdbus output uses a Python-like mapping; attempt to extract the
            # '/org/bluez/...' path token from the line.
            parts = line.split("'")
            for part in parts:
                if part.startswith(dev_path):
                    candidate = part.strip()
                    # Verify the candidate actually implements MediaPlayer1 by
                    # reading a known property. If the property query fails,
                    # treat this candidate as invalid and continue searching.
                    try:
                        verify_cmd = [
                            "gdbus",
                            "call",
                            "--system",
                            "--dest",
                            "org.bluez",
                            "--object-path",
                            candidate,
                            "--method",
                            "org.freedesktop.DBus.Properties.Get",
                            "org.bluez.MediaPlayer1",
                            "PlaybackStatus",
                        ]
                        verify = subprocess.run(
                            verify_cmd, capture_output=True, text=True, check=False
                        )
                    except FileNotFoundError:
                        raise RuntimeError("gdbus not found; install libglib2.0-bin")
                    if verify.returncode == 0:
                        return candidate
                    # otherwise continue searching other lines
    return None


def _call_player_method(mac: str, method: str) -> None:
    player = _find_player_path(mac)
    if not player:
        # No explicit MediaPlayer1 object found under the device. Some
        # BlueZ stacks expose deprecated MediaControl1 methods on the
        # device path itself. Try calling the method there, but first
        # check if the device's MediaControl1 reports Connected=True.
        dev_path = _mac_to_path(mac)
        # Check MediaControl1 Connected property
        try:
            prop_cmd = [
                "gdbus",
                "call",
                "--system",
                "--dest",
                "org.bluez",
                "--object-path",
                dev_path,
                "--method",
                "org.freedesktop.DBus.Properties.Get",
                "org.bluez.MediaControl1",
                "Connected",
            ]
            prop = subprocess.run(prop_cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            raise RuntimeError("gdbus not found; install libglib2.0-bin")
        if prop.returncode != 0:
            stderr = (prop.stderr or "").strip()
            stdout = (prop.stdout or "").strip()
            details = stderr or stdout or f"exit code {prop.returncode}"
            raise RuntimeError(f"Unable to query MediaControl1 properties: {details}")
        # prop.stdout looks like: '(true,)' or '(false,)'
        connected = "true" in (prop.stdout or "").lower()
        if not connected:
            raise RuntimeError(
                "Device MediaControl1 reports Connected=false; connect the device first (e.g. `bluetoothctl connect <MAC>`)."
            )
        # If connected, call the MediaControl1 method on the device path.
        cmd = [
            "gdbus",
            "call",
            "--system",
            "--dest",
            "org.bluez",
            "--object-path",
            dev_path,
            "--method",
            f"org.bluez.MediaControl1.{method}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            raise RuntimeError("gdbus not found; install libglib2.0-bin")
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            details = stderr or stdout or f"exit code {result.returncode}"
            raise RuntimeError(f"gdbus command failed on MediaControl1: {details}")
        return
    cmd = [
        "gdbus",
        "call",
        "--system",
        "--dest",
        "org.bluez",
        "--object-path",
        player,
        "--method",
        f"org.bluez.MediaPlayer1.{method}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise RuntimeError("gdbus not found; install libglib2.0-bin")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr or stdout or f"exit code {result.returncode}"
        # If MediaPlayer1 call fails, attempt a MediaControl1 fallback when
        # the device reports Connected=true. This helps on stacks that only
        # implement deprecated MediaControl1 methods on the device path.
        dev_path = _mac_to_path(mac)
        try:
            prop_cmd = [
                "gdbus",
                "call",
                "--system",
                "--dest",
                "org.bluez",
                "--object-path",
                dev_path,
                "--method",
                "org.freedesktop.DBus.Properties.Get",
                "org.bluez.MediaControl1",
                "Connected",
            ]
            prop = subprocess.run(prop_cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            raise RuntimeError("gdbus not found; install libglib2.0-bin")
        connected = False
        if prop.returncode == 0:
            connected = "true" in (prop.stdout or "").lower()
        if connected:
            # Try MediaControl1 fallback
            fall_cmd = [
                "gdbus",
                "call",
                "--system",
                "--dest",
                "org.bluez",
                "--object-path",
                dev_path,
                "--method",
                f"org.bluez.MediaControl1.{method}",
            ]
            try:
                fall = subprocess.run(fall_cmd, capture_output=True, text=True, check=False)
            except FileNotFoundError:
                raise RuntimeError("gdbus not found; install libglib2.0-bin")
            if fall.returncode == 0:
                return
            fall_details = (fall.stderr or "").strip() or (fall.stdout or "").strip()
            raise RuntimeError(
                f"MediaPlayer1 call failed: {details}; MediaControl1 fallback also failed: {fall_details}"
            )
        # Not connected or fallback not available — surface original error
        raise RuntimeError(f"gdbus command failed: {details}")


def _run_bluetoothctl(address: str, command: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["bluetoothctl", command, address],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("bluetoothctl not found. Install bluez or bluez-tools") from error


def _ensure_media_connected(mac: str, attempts: int = 2, delay: float = 1.0) -> None:
    dev_path = _mac_to_path(mac)
    for attempt in range(attempts + 1):
        try:
            prop_cmd = [
                "gdbus",
                "call",
                "--system",
                "--dest",
                "org.bluez",
                "--object-path",
                dev_path,
                "--method",
                "org.freedesktop.DBus.Properties.Get",
                "org.bluez.MediaControl1",
                "Connected",
            ]
            prop = subprocess.run(prop_cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            raise RuntimeError("gdbus not found; install libglib2.0-bin")
        if prop.returncode == 0 and "true" in (prop.stdout or "").lower():
            return
        if attempt >= attempts:
            break
        # try to connect via bluetoothctl and retry
        connect = _run_bluetoothctl(mac, "connect")
        if connect.returncode != 0:
            # give the adapter a moment, then retry regardless to surface clearer error
            time.sleep(delay)
        else:
            time.sleep(delay)
    raise RuntimeError("Media controller not connected; ensure the device is paired and reachable")


def play(mac: str) -> None:
    _ensure_media_connected(mac)
    _call_player_method(mac, "Play")


def pause(mac: str) -> None:
    _ensure_media_connected(mac)
    _call_player_method(mac, "Pause")


def next_track(mac: str) -> None:
    _ensure_media_connected(mac)
    _call_player_method(mac, "Next")


def previous_track(mac: str) -> None:
    _ensure_media_connected(mac)
    _call_player_method(mac, "Previous")


def volume_up(mac: str) -> None:
    _ensure_media_connected(mac)
    _call_player_method(mac, "VolumeUp")


def volume_down(mac: str) -> None:
    _ensure_media_connected(mac)
    _call_player_method(mac, "VolumeDown")
