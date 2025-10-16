"""Helper to call BlueZ MediaPlayer methods via gdbus.

This uses the system bus gdbus binary to avoid dbus-next compatibility issues
observed on some Pi setups.
"""
import shlex
import subprocess
from typing import Optional


def _mac_to_path(mac: str) -> str:
    return "/org/bluez/hci0/dev_" + mac.replace(":", "_")


def _find_player_path(mac: str) -> Optional[str]:
    dev_path = _mac_to_path(mac)
    # Try common player path suffixes
    candidates = [f"{dev_path}/player0", f"{dev_path}/player1"]
    for p in candidates:
        cmd = ["gdbus", "introspect", "--system", "--dest", "org.bluez", "--object-path", p]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return p
        except subprocess.CalledProcessError:
            continue
        except FileNotFoundError:
            raise RuntimeError("gdbus not found; install libglib2.0-bin")
    # If none found, return None
    return None


def _call_player_method(mac: str, method: str) -> None:
    player = _find_player_path(mac)
    if not player:
        raise RuntimeError("Media player object not found for device")
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
    subprocess.run(cmd, check=True)


def play(mac: str) -> None:
    _call_player_method(mac, "Play")


def pause(mac: str) -> None:
    _call_player_method(mac, "Pause")


def next_track(mac: str) -> None:
    _call_player_method(mac, "Next")


def previous_track(mac: str) -> None:
    _call_player_method(mac, "Previous")
