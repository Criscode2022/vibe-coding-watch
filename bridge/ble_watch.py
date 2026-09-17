"""Keep a BLE session to the ZTE Live 3 and push IDO notifications."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from bleak import BleakClient, BleakScanner

from speaker import announce_counts
from ido import (
    NOTIFY_BULK,
    NOTIFY_CMD,
    WRITE_CMD,
    bind_start,
    dnd_off,
    enable_notice,
    encode_call,
    encode_miband,
    find_watch,
    get_battery,
    get_device_info,
    get_func_table,
    get_notice_status,
    open_ancs,
    raise_to_wake,
    set_time,
    weather_city,
    weather_data,
    weather_on,
)

log = logging.getLogger("vibeos.ble")

WATCH_BLE = "41:42:C6:70:B4:41"
WATCH_NAME = "ZTE WATCH Live3_B441"


class WatchRadio:
    def __init__(self) -> None:
        self.client: BleakClient | None = None
        self.connected = False
        self.last_error: str | None = None
        self.last_rx: list[str] = []
        self.last_push: str | None = None
        self.last_push_at: float = 0
        self.device_name = WATCH_NAME
        self.address = WATCH_BLE
        self.battery_pct: int | None = None
        self.on_rx: Callable[[bytes], None] | None = None
        self.last_tx: str | None = None
        self.lock = asyncio.Lock()
        self._rx_event = asyncio.Event()
        self.alerts_armed = False

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "address": self.address,
            "name": self.device_name,
            "error": self.last_error,
            "last_push": self.last_push,
            "last_tx": self.last_tx,
            "battery": self.battery_pct,
            "alerts_armed": self.alerts_armed,
            "last_rx": self.last_rx[-6:],
        }

    def _on_notify(self, _handle: int, data: bytearray) -> None:
        raw = bytes(data)
        hx = raw.hex(" ")
        self.last_rx.append(hx)
        self.last_rx = self.last_rx[-20:]
        if len(raw) >= 7 and raw[0] == 0x02 and raw[1] == 0x05:
            self.battery_pct = raw[6]
        self._rx_event.set()
        log.info("RX %s", hx)
        if self.on_rx:
            self.on_rx(raw)

    async def _resolve(self) -> str:
        try:
            found = await BleakScanner.find_device_by_address(WATCH_BLE, timeout=6.0)
            if found:
                return found.address
        except Exception as exc:
            log.warning("scan by address failed: %s", exc)
        devices = await BleakScanner.discover(timeout=6.0)
        for dev in devices:
            name = dev.name or ""
            if "Live3" in name or name == WATCH_NAME:
                self.device_name = name
                self.address = dev.address
                return dev.address
        return WATCH_BLE

    async def connect(self) -> bool:
        address = await self._resolve()
        self.address = address
        client = BleakClient(address, timeout=20.0)
        await client.connect()
        try:
            await client.start_notify(NOTIFY_CMD, self._on_notify)
        except Exception as exc:
            log.warning("notify cmd: %s", exc)
        try:
            await client.start_notify(NOTIFY_BULK, self._on_notify)
        except Exception as exc:
            log.warning("notify bulk: %s", exc)
        self.client = client
        self.last_error = None
        await self._write(get_device_info())
        await self._write(get_func_table())
        await self._write(get_battery())
        await self._write(get_notice_status())
        await self._write(set_time())
        await self.arm_alerts()
        self.connected = True
        return True

    async def _write(self, payload: bytes) -> None:
        if not self.client or not self.client.is_connected:
            raise RuntimeError("watch not connected")
        self.last_tx = payload.hex(" ")
        log.info("TX %s", self.last_tx)
        self._rx_event.clear()
        try:
            await self.client.write_gatt_char(WRITE_CMD, payload, response=True)
        except Exception:
            await self.client.write_gatt_char(WRITE_CMD, payload, response=False)
        try:
            await asyncio.wait_for(self._rx_event.wait(), timeout=0.8)
        except asyncio.TimeoutError:
            pass

    async def arm_alerts(self) -> None:
        for pkt in enable_notice():
            await self._write(pkt)
        await self._write(open_ancs())
        await self._write(raise_to_wake())
        await self._write(dnd_off())
        await self._write(weather_on())
        await self._write(bind_start())
        self.alerts_armed = True

    async def push_visible(
        self,
        title: str,
        body: str,
        working: int = 1,
        ended: int = 0,
        attention: int = 0,
        loud: bool = True,
        event: str | None = None,
    ) -> None:
        async with self.lock:
            text = f"{title} {body}".strip()
            if loud:
                await asyncio.to_thread(announce_counts, working, ended, attention, event)
            await self._write(weather_data(working, ended, attention))
            await self._write(weather_city("VIBEOS"))
            await self._write(encode_miband(text[:18]))
            for frame in encode_call(title[:12], "1"):
                await self._write(frame)
            self.last_push = f"{title}: {body}"
            self.last_push_at = time.time()

    async def speak_counts(
        self,
        working: int,
        ended: int,
        attention: int,
        event: str | None = None,
    ) -> None:
        await asyncio.to_thread(announce_counts, working, ended, attention, event)
        self.last_push = event or f"{working} {ended} {attention}"
        self.last_push_at = time.time()

    async def push_message(
        self,
        title: str,
        body: str,
        *,
        alert: bool = False,
        working: int = 0,
        ended: int = 0,
        attention: int = 0,
        event: str | None = None,
    ) -> None:
        await self.speak_counts(working, ended, attention, event)

    async def ping_find(self) -> None:
        async with self.lock:
            await self._write(find_watch())
            for frame in encode_call("VibeOS", "1"):
                await self._write(frame)

    async def close(self) -> None:
        client = self.client
        self.client = None
        self.connected = False
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                if not self.connected:
                    log.info("connecting to %s", WATCH_BLE)
                    await self.connect()
                    log.info("watch radio up")
                else:
                    if self.client and not self.client.is_connected:
                        self.connected = False
                        continue
                    await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = repr(exc)
                self.connected = False
                log.warning("watch radio: %s", exc)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=4.0)
                except asyncio.TimeoutError:
                    pass
        await self.close()
