#!/usr/bin/env python3
"""Simple BLE GATT write test using Bleak.

Usage:
  python ble_write_test.py <address> <char_uuid> <payload-hex>

Example:
  python ble_write_test.py 78:BD:BC:96:AC:07 0000ff01-0000-1000-8000-00805f9b34fb 01

This will connect to the device, write the bytes represented by payload-hex
to the characteristic, and print the result.
"""
import asyncio
import sys
from typing import Optional

from bleak import BleakClient


async def run(address: str, char_uuid: str, payload_hex: str) -> int:
    try:
        payload = bytes.fromhex(payload_hex)
    except Exception as e:
        print(f"Invalid payload hex: {e}")
        return 2

    print(f"Connecting to {address}...")
    try:
        async with BleakClient(address, timeout=10.0) as client:
            if not client.is_connected:
                print("Failed to connect")
                return 3
            print("Connected")
            print(f"Writing to {char_uuid}: {payload.hex()}")
            try:
                await client.write_gatt_char(char_uuid, payload, response=True)
                print("Write successful")
                return 0
            except Exception as e:
                print(f"Write failed: {e}")
                return 4
    except Exception as e:
        print(f"Connection error: {e}")
        return 5


def main(argv: Optional[list] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 3:
        print("Usage: python ble_write_test.py <address> <char_uuid> <payload-hex>")
        return 1
    address, char_uuid, payload_hex = argv
    return asyncio.run(run(address, char_uuid, payload_hex))


if __name__ == '__main__':
    raise SystemExit(main())
