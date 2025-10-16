"""Small helper to start a BlueZ DBus agent and keep it running.

This script is optional: the main FastAPI startup now calls
`manager.bluetooth._ensure_agent()` which will attempt DBus agent
registration. Use this script if you'd like a lightweight separate
agent process managed by systemd.

Run with the backend venv activated (same env as backend service):

    python run_agent.py

"""

import asyncio
import logging
import subprocess
import sys
import shutil
import os
from typing import Optional
from pathlib import Path

logging.basicConfig(level=logging.INFO)


def _start_bluetoothctl_agent():
    """Start an interactive bluetoothctl process and register an agent there.

    This is a pragmatic fallback for systems where dbus-next can't register
    a ServiceInterface. An interactive bluetoothctl session will register an
    agent in that process which will remain active while the process runs.
    """
    # Locate bluetoothctl executable. Prefer shutil.which but also try
    # common absolute locations because systemd services may run with a
    # restricted PATH.
    def _find_btctl() -> Optional[str]:
        path = shutil.which("bluetoothctl")
        if path:
            return path
        candidates = ["/usr/bin/bluetoothctl", "/bin/bluetoothctl", "/usr/local/bin/bluetoothctl"]
        for c in candidates:
            try:
                if Path(c).exists():
                    return c
            except Exception:
                continue
        return None

    # Try a few times in case PATH or packages are still settling during boot.
    attempts = 5
    delay = 0.5
    proc = None
    for attempt in range(attempts):
        btctl = _find_btctl()
        if not btctl:
            logging.debug('Attempt %d/%d: bluetoothctl not found yet', attempt + 1, attempts)
            asyncio.sleep(delay) if attempt < attempts - 1 else None
            continue
        try:
            proc = subprocess.Popen(
                [btctl], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            break
        except FileNotFoundError:
            logging.exception('bluetoothctl not found at %s on attempt %d', btctl, attempt + 1)
            proc = None
            asyncio.sleep(delay) if attempt < attempts - 1 else None

    if proc is None:
        logging.error('bluetoothctl not found in PATH or common locations after %d attempts; cannot start agent', attempts)
        return None

    def send(cmd: str) -> None:
        try:
            proc.stdin.write(cmd + "\n")
            proc.stdin.flush()
        except Exception:
            logging.exception('Failed to write to bluetoothctl stdin')

    # Register an agent with configured capability and make it default
    cap = os.getenv('OMNICONTROL_BLUEZ_AGENT_CAP', 'NoInputNoOutput')
    send(f"agent {cap}")
    send("default-agent")
    logging.info('Started bluetoothctl interactive session as agent (pid=%s)', proc.pid)
    return proc


async def main():
    # Try importing and starting the dbus-next agent at runtime. Import-time
    # failures are common on some systems/versions of dbus-next, so perform the
    # import inside the try block and fall back to bluetoothctl if anything
    # goes wrong.
    # Import may raise library-specific errors; handle import and start separately
    BluezAgent = None
    try:
        from controllers.bluez_agent import BluezAgent  # type: ignore
    except Exception as e:  # pragma: no cover - runtime-dependent
        # dbus-next / annotation issues are common on some Pi setups. Log the
        # concise error (no stack trace) and fall back to bluetoothctl.
        logging.info('BlueZ DBus agent import failed: %s', e)

    if BluezAgent is not None:
        try:
            import os

            cap = os.getenv('OMNICONTROL_BLUEZ_AGENT_CAP', None)
            agent = BluezAgent(capability=cap) if cap is not None else BluezAgent()
            await agent.start()
            logging.info('BlueZ DBus agent started and registered. Running until interrupted.')
            # Keep running
            while True:
                await asyncio.sleep(3600)
        except Exception as e:  # pragma: no cover - runtime-dependent
            # Agent registration/start can also fail due to dbus-next runtime
            # differences. Log succinctly and fall back to the bluetoothctl agent.
            logging.info('BlueZ DBus agent failed to start: %s', e)

    # Fall through to bluetoothctl fallback
    # Try starting the bluetoothctl fallback in a loop — don't exit the
    # service if the binary is temporarily unavailable. This avoids
    # systemd repeatedly marking the unit as failed during transient boot
    # conditions.
    proc = await asyncio.to_thread(_start_bluetoothctl_agent)
    retry_interval = 5
    while proc is None:
        logging.warning('No agent available yet; retrying in %s seconds', retry_interval)
        try:
            await asyncio.sleep(retry_interval)
        except asyncio.CancelledError:
            logging.info('run_agent received cancel while waiting for agent; exiting')
            return
        proc = await asyncio.to_thread(_start_bluetoothctl_agent)

    # Keep process alive; the bluetoothctl process will maintain the agent
    # registration while running. Monitor until cancellation.
    try:
        logging.info('Agent process running (pid=%s); run_agent entering wait loop', proc.pid)
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logging.info('run_agent received cancel; terminating bluetoothctl')
        try:
            proc.terminate()
        except Exception:
            logging.exception('Failed to terminate bluetoothctl process')


if __name__ == '__main__':
    asyncio.run(main())
