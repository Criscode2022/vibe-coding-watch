"""Probe the paired ZTE Watch Live 3 over Bluetooth LE."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from bleak import BleakClient, BleakScanner

WATCH_MAC = "41:42:F9:70:B4:41"
WATCH_NAME_HINTS = ("ZTE", "Live3", "WATCH", "SW2301")
OUT = Path(__file__).resolve().parent.parent / "data" / "ble_probe.json"


def _interesting(name: str | None) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(h.upper() in upper for h in WATCH_NAME_HINTS)


async def main() -> int:
    print("Scanning BLE (12s)...")
    devices = await BleakScanner.discover(timeout=12.0, return_adv=True)
    found = []
    target = None
    for device, adv in devices.values():
        rec = {
            "address": device.address,
            "name": device.name or adv.local_name,
            "rssi": adv.rssi,
            "uuids": list(adv.service_uuids or []),
            "mfr": {str(k): v.hex() for k, v in (adv.manufacturer_data or {}).items()},
        }
        found.append(rec)
        addr = (device.address or "").replace("-", ":").upper()
        if addr == WATCH_MAC or _interesting(rec["name"]):
            target = rec
            print(f"MATCH {rec['address']} {rec['name']} rssi={rec['rssi']} uuids={rec['uuids']}")

    print(f"Saw {len(found)} BLE advertisers")
    if target is None:
        # Windows sometimes reports the device without advertising.
        print(f"No advertiser matched; trying bonded address {WATCH_MAC}")
        target = {"address": WATCH_MAC, "name": "bonded"}

    gatt = {"address": target["address"], "services": [], "error": None}
    try:
        async with BleakClient(target["address"], timeout=20.0) as client:
            gatt["connected"] = bool(client.is_connected)
            gatt["mtu"] = getattr(client, "mtu_size", None)
            print(f"Connected={client.is_connected} mtu={gatt['mtu']}")
            for svc in client.services:
                svc_rec = {"uuid": svc.uuid, "description": svc.description, "characteristics": []}
                print(f"SVC {svc.uuid} {svc.description}")
                for ch in svc.characteristics:
                    ch_rec = {
                        "uuid": ch.uuid,
                        "description": ch.description,
                        "properties": list(ch.properties),
                        "handle": ch.handle,
                    }
                    if "read" in ch.properties:
                        try:
                            raw = await client.read_gatt_char(ch.uuid)
                            ch_rec["value_hex"] = raw.hex()
                            try:
                                ch_rec["value_text"] = raw.decode("utf-8", "replace")
                            except Exception:
                                pass
                        except Exception as exc:
                            ch_rec["read_error"] = str(exc)
                    print(f"  CH {ch.uuid} {ch.properties} {ch_rec.get('value_hex', '')}")
                    svc_rec["characteristics"].append(ch_rec)
                gatt["services"].append(svc_rec)
    except Exception as exc:
        gatt["error"] = repr(exc)
        print(f"GATT error: {exc!r}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"advertisers": found, "target": target, "gatt": gatt}
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0 if gatt.get("connected") else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
