#!/usr/bin/env python3
"""Discover GATT services and characteristics for a BLE device.

Usage:
  python ble_discover.py <address>

Example:
  python ble_discover.py 68:72:C3:FC:4B:43

This connects to the device and prints all services and their characteristics.
"""
import asyncio
import sys
from typing import Optional

from bleak import BleakClient


async def discover(address: str) -> int:
    print(f"Connecting to {address}...")
    client = BleakClient(address, timeout=20.0)
    try:
        await client.connect()
        if not client.is_connected:
            print("Failed to connect")
            return 2
        print("Connected")

        svcs = None
        # Try multiple ways to fetch services depending on Bleak version
        try:
            if hasattr(client, 'get_services'):
                svcs = await client.get_services()
            else:
                # some Bleak versions expose a cached .services attribute
                svcs = getattr(client, 'services', None)
                # if still None, try calling get_services anyway (may raise)
                if svcs is None and hasattr(client, 'get_services'):
                    svcs = await client.get_services()
        except EOFError as eof:
            # dbus transport EOF can happen; attempt to continue with any cached services
            print("EOF while fetching services:", repr(eof))
            svcs = getattr(client, 'services', None)
        except AttributeError:
            # older/newer Bleak APIs may not have get_services; fall back to .services
            svcs = getattr(client, 'services', None)

        if not svcs:
            print("No services discovered (services empty or unavailable on this Bleak version)")
            return 4

        for service in svcs:
            print(f"Service {service.uuid} - {service.description}")
            for char in service.characteristics:
                props = []
                try:
                    if getattr(char.properties, 'read', False):
                        props.append('read')
                    if getattr(char.properties, 'write', False):
                        props.append('write')
                    if getattr(char.properties, 'notify', False):
                        props.append('notify')
                except Exception:
                    # Some backends expose properties differently; ignore and continue
                    pass
                props_str = ','.join(props) if props else 'none'
                print(f"  Characteristic {char.uuid} ({props_str})")
                for desc in getattr(char, 'descriptors', []):
                    try:
                        print(f"    Descriptor {desc.handle}")
                    except Exception:
                        pass
        return 0
    except Exception as e:
        import traceback

        print("Error discovering services:")
        print(repr(e))
        traceback.print_exc()
        return 3
    finally:
        # Ensure we attempt a graceful disconnect but don't fail hard if the
        # underlying dbus transport raises EOFError on disconnect.
        try:
            await client.disconnect()
        except EOFError as eof:
            print("EOF during disconnect (ignored):", repr(eof))
        except Exception:
            # swallow other disconnect errors to avoid masking discovery output
            pass


def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print("Usage: python ble_discover.py <address>")
        return 1
    return asyncio.run(discover(argv[0]))


if __name__ == '__main__':
    raise SystemExit(main())
