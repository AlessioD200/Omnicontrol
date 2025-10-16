from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

from bleak import BleakClient, BleakScanner
try:
    from .bluez_agent import BluezAgent
except Exception:
    BluezAgent = None

logger = logging.getLogger(__name__)


@dataclass
class BluetoothDevice:
    identifier: str
    name: str
    address: str
    rssi: Optional[int]

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.identifier,
            "name": self.name,
            "address": self.address,
            "rssi": self.rssi,
        }


class BluetoothController:
    """Wraps Bleak helpers for scanning and simple control calls."""

    def __init__(self, default_timeout: int = 10) -> None:
        self._default_timeout = default_timeout
        import os

        # Allow the agent capability to be configured via env var. Some devices
        # require a different capability (e.g. DisplayYesNo) to show a passkey
        # and allow confirmation.
        self._agent_mode = os.getenv("OMNICONTROL_BLUEZ_AGENT_CAP", "NoInputNoOutput")
        self._agent_ready = False
        self._agent_lock = asyncio.Lock()

    async def scan(self, timeout: Optional[int] = None) -> List[BluetoothDevice]:
        """Discover nearby BLE peripherals."""
        scan_timeout = timeout or self._default_timeout
        devices = await BleakScanner.discover(timeout=scan_timeout)
        results: List[BluetoothDevice] = []
        for device in devices:
            identifier = device.address.lower().replace(":", "")
            rssi = getattr(device, "rssi", None)
            if rssi is None:
                metadata = getattr(device, "metadata", {}) or {}
                rssi = metadata.get("rssi")
            if rssi is None:
                details = getattr(device, "details", {})
                if isinstance(details, dict):
                    rssi = details.get("RSSI") or details.get("rssi")
            results.append(
                BluetoothDevice(
                    identifier=identifier,
                    name=device.name or device.address,
                    address=device.address,
                    rssi=rssi,
                )
            )
        # Also include Classic (BR/EDR) devices discovered via bluetoothctl.
        try:
            classic = await asyncio.to_thread(self._scan_classic_devices)
            # Merge, prefer BLE entries (with RSSI) when available
            seen = {d.address.upper(): d for d in results}
            for c in classic:
                if c.address.upper() in seen:
                    # update name if BLE name missing
                    existing = seen[c.address.upper()]
                    if (not existing.name or existing.name == existing.address) and c.name:
                        existing.name = c.name
                else:
                    results.append(c)
        except Exception:
            logger.debug('classic bluetooth scan failed, continuing with BLE-only scan', exc_info=True)

        return results

    def _scan_classic_devices(self) -> List[BluetoothDevice]:
        """Run `bluetoothctl devices` and `bluetoothctl paired-devices` to list Classic Bluetooth devices.

        Returns list of BluetoothDevice with rssi=None.
        """
        devices: List[BluetoothDevice] = []
        # devices (discovered) and paired-devices
        for cmd in (["devices"], ["paired-devices"]):
            try:
                result = self._run_bluetoothctl(list(cmd))
            except RuntimeError:
                # bluetoothctl not present
                continue
            out = (result.stdout or '').strip()
            if not out:
                continue
            for line in out.splitlines():
                # Expect lines like: "Device AA:BB:CC:DD:EE:FF DeviceName"
                parts = line.strip().split(' ', 2)
                if len(parts) < 2:
                    continue
                # parts[1] should be the MAC
                address = parts[1].strip()
                name = parts[2].strip() if len(parts) >= 3 else address
                identifier = address.lower().replace(':', '')
                devices.append(BluetoothDevice(identifier=identifier, name=name, address=address, rssi=None))
        return devices

    async def ping(self, address: str) -> bool:
        """Open a transient connection to verify reachability."""
        try:
            async with BleakClient(address, timeout=self._default_timeout) as client:
                connected = client.is_connected
                await asyncio.sleep(0.5)
                return connected
        except EOFError:
            # dbus_fast sometimes raises raw EOFError when the system bus connection
            # is closed (bluetoothd restart, dbus socket issues). Treat as unreachable
            # and log for diagnostics.
            logger.warning("DBus EOFError during Bleak ping for %s", address, exc_info=True)
            return False
        except Exception:
            logger.debug("BLE ping failed for %s", address, exc_info=True)
            return False

    async def connect(self, address: str, timeout: Optional[int] = None) -> bool:
        """Attempt to establish a BLE connection and immediately close it. Returns True if connected."""
        try:
            t = timeout or self._default_timeout
            async with BleakClient(address, timeout=t) as client:
                return bool(client.is_connected)
        except EOFError:
            logger.warning("DBus EOFError during Bleak connect for %s", address, exc_info=True)
            return False
        except Exception:
            logger.debug("BLE connect failed for %s", address, exc_info=True)
            return False

    async def toggle_power(
        self,
        address: str,
        *,
        characteristic: Optional[str] = None,
        turn_on: Optional[bool] = None,
    ) -> bool:
        """Toggle a device on/off via a writable GATT characteristic."""
        if turn_on is None:
            raise ValueError("turn_on must be provided for BLE toggles")

        try:
            async with BleakClient(address, timeout=self._default_timeout) as client:
                if characteristic:
                    payload = bytes([0x01 if turn_on else 0x00])
                    await client.write_gatt_char(characteristic, payload, response=True)
                return turn_on
        except EOFError:
            logger.exception("DBus EOFError while toggling power for %s", address)
            raise RuntimeError("BLE backend DBus connection closed unexpectedly; restart bluetoothd and retry")
        except Exception:
            logger.exception("Failed to toggle power for %s", address)
            raise

    async def send_command(
        self,
        address: str,
        *,
        characteristic: str,
        payload: bytes,
        with_response: bool = False,
    ) -> None:
        """Write an arbitrary payload to a characteristic for control commands."""
        if not characteristic:
            raise ValueError("Characteristic UUID required for BLE command")

        try:
            async with BleakClient(address, timeout=self._default_timeout) as client:
                await client.write_gatt_char(characteristic, payload, response=with_response)
        except EOFError:
            logger.exception("DBus EOFError while writing characteristic %s on %s", characteristic, address)
            raise RuntimeError("BLE backend DBus connection closed unexpectedly; restart bluetoothd and retry")
        except Exception:
            logger.exception("Failed to write characteristic %s on %s", characteristic, address)
            raise

    async def pair_and_trust(self, address: str, timeout: int = 15) -> None:
        """Ensure the device is paired and trusted with the system Bluetooth stack."""
        normalized = self._normalize_bt_address(address)

        # First, try a direct BLE GATT connection using Bleak. Many BLE peripherals
        # allow control without being 'paired' at the BlueZ level. This mirrors the
        # Harmony-style behaviour: attempt a simple connect and skip system pairing
        # when possible to keep things simple for the user.
        try:
            try_connect_timeout = min(5, timeout)
            async with BleakClient(normalized, timeout=try_connect_timeout) as client:
                if client.is_connected:
                    logger.info("Connected to %s via Bleak without system pairing", normalized)
                    return
        except Exception as exc:  # pragma: no cover - runtime-dependent
            logger.debug("direct Bleak connect failed for %s, falling back to system pairing: %s", normalized, exc)

        # If direct BLE connect didn't succeed, fall back to system-level pairing.
        await self._ensure_agent()
        discovery_window = max(3, min(timeout, 20))
        scan_result = await asyncio.to_thread(
            self._run_bluetoothctl,
            ["--timeout", str(discovery_window), "scan", "on"],
        )
        if scan_result.returncode != 0:
            logger.warning(
                "bluetoothctl scan on failed before pairing %s: %s", normalized, self._format_bt_error("scan", "on", scan_result)
            )
        else:
            await asyncio.to_thread(self._run_bluetoothctl, ["scan", "off"])

        pair_result = await asyncio.to_thread(self._run_bluetoothctl, ["--timeout", str(timeout), "pair", normalized])
        if pair_result.returncode != 0 and not self._is_already_paired(pair_result.stderr, pair_result.stdout):
            raise RuntimeError(self._format_bt_error("pair", normalized, pair_result))

        trust_result = await asyncio.to_thread(self._run_bluetoothctl, ["--timeout", str(5), "trust", normalized])
        if trust_result.returncode != 0 and not self._is_already_trusted(trust_result.stderr, trust_result.stdout):
            raise RuntimeError(self._format_bt_error("trust", normalized, trust_result))

    async def _ensure_agent(self) -> None:
        async with self._agent_lock:
            if self._agent_ready:
                return
            # Prefer a DBus-based agent if available (dbus-next). This allows the hub
            # to programmatically confirm/passkey pairing interactions required by
            # some devices (e.g. Android TV boxes). If that fails, fall back to
            # bluetoothctl orchestration.
            if BluezAgent is not None:
                try:
                    agent = BluezAgent(capability=self._agent_mode)
                    await agent.start()
                    logger.info('DBus BlueZ agent started')
                    self._agent_ready = True
                    return
                except Exception:
                    logger.exception('DBus BlueZ agent failed; falling back to bluetoothctl')

            # bluetoothctl fallback (existing behavior)
            agent_result = await asyncio.to_thread(self._run_bluetoothctl, ["agent", self._agent_mode])
            if agent_result.returncode != 0:
                logger.warning("bluetoothctl agent %s returned %s; stdout=%s stderr=%s",
                               self._agent_mode, agent_result.returncode,
                               (agent_result.stdout or '').strip(), (agent_result.stderr or '').strip())

            # Try to make the agent the default. If that fails, attempt a register fallback
            default_result = await asyncio.to_thread(self._run_bluetoothctl, ["default-agent"])
            if default_result.returncode != 0:
                logger.warning("bluetoothctl default-agent failed: stdout=%s stderr=%s",
                               (default_result.stdout or '').strip(), (default_result.stderr or '').strip())

                register_result = await asyncio.to_thread(
                    self._run_bluetoothctl,
                    ["--timeout", "5", "register", "agent", self._agent_mode],
                )
                if register_result.returncode != 0:
                    logger.warning("bluetoothctl register agent failed: stdout=%s stderr=%s",
                                   (register_result.stdout or '').strip(), (register_result.stderr or '').strip())
                else:
                    default_result = await asyncio.to_thread(self._run_bluetoothctl, ["default-agent"])

                if default_result.returncode != 0:
                    raise RuntimeError(
                        "unable to register/default the bluetooth agent: " +
                        self._format_bt_error("default-agent", "", default_result)
                    )

            self._agent_ready = True

    def _normalize_bt_address(self, address: str) -> str:
        """Normalize various MAC representations to colon-separated upper-case format.

        Accepts forms like:
        - "aabbccddeeff"
        - "aa_bb_cc_dd_ee_ff"
        - "AA:BB:CC:DD:EE:FF"
        - "dev_AA:BB:CC:DD:EE:FF"
        Returns e.g. "AA:BB:CC:DD:EE:FF".
        """
        if not address:
            raise ValueError("empty bluetooth address")
        s = address.strip()
        # Drop common prefixes used by UIs or debug prints
        s = re.sub(r'(?i)^(dev[_:-]?|device[_:-]?|bluetooth:)', '', s)
        # Extract hex characters only
        hex_chars = re.findall(r'[0-9A-Fa-f]', s)
        hex_str = ''.join(hex_chars)
        if len(hex_str) == 12:
            pairs = [hex_str[i : i + 2] for i in range(0, 12, 2)]
            return ':'.join(pairs).upper()
        # If it already contains separators but wasn't caught above, try to normalize by
        # splitting on non-hex separators and reformatting
        parts = re.split(r'[^0-9A-Fa-f]+', s)
        parts = [p for p in parts if p]
        joined = ''.join(parts)
        if len(joined) == 12:
            pairs = [joined[i : i + 2] for i in range(0, 12, 2)]
            return ':'.join(pairs).upper()
        # Otherwise fall back to uppercasing the original and hope for the best (will likely error later)
        return s.upper()

    def _run_bluetoothctl(self, args: List[str]) -> subprocess.CompletedProcess:
        cmd = ["bluetoothctl"] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            logger.debug("bluetoothctl %s -> %s", " ".join(args), result.returncode)
            if result.stdout:
                logger.debug("stdout: %s", result.stdout.strip())
            if result.stderr:
                logger.debug("stderr: %s", result.stderr.strip())
            return result
        except FileNotFoundError as error:
            raise RuntimeError("bluetoothctl not found. Install bluez-utils or bluez package.") from error

    @staticmethod
    def _is_already_paired(stderr: Optional[str], stdout: Optional[str]) -> bool:
        text = " ".join(filter(None, [stderr or "", stdout or ""]))
        tokens = text.lower()
        return "already paired" in tokens or "alreadyexists" in tokens or "already exists" in tokens

    @staticmethod
    def _is_already_trusted(stderr: Optional[str], stdout: Optional[str]) -> bool:
        text = " ".join(filter(None, [stderr or "", stdout or ""]))
        tokens = text.lower()
        return "already trusted" in tokens or "trusted devices:" in tokens

    @staticmethod
    def _format_bt_error(action: str, target: str, result: subprocess.CompletedProcess) -> str:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        details = stderr or stdout or f"exit code {result.returncode}"
        return f"bluetoothctl {action} {target} failed: {details}"
