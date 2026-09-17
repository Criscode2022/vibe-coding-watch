"""One-shot: connect Live 3, get info, find-watch, send VibeOS message."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ble_watch import WatchRadio


async def main() -> int:
    radio = WatchRadio()
    print("connecting...")
    await radio.connect()
    print("connected", radio.status())
    await asyncio.sleep(0.6)
    print("find watch")
    await radio.ping_find()
    await asyncio.sleep(1.2)
    print("push message")
    await radio.push_message("VibeOS", "2 work 0 attn")
    await asyncio.sleep(2.0)
    print("rx", radio.last_rx)
    await radio.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
