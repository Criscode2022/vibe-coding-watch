"""VibeOS: Mac Mini agent API + optional local watch radio."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIBEOS = ROOT / "vibeos"
DATA = ROOT / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector import snapshot  # noqa: E402

log = logging.getLogger("vibeos")
STATE_LOCK = threading.Lock()
STATE: dict = {
    "working": 0,
    "ended": 0,
    "attention": 0,
    "watch": {},
    "event": None,
    "ts": 0,
    "source": None,
}
RADIO = None
SPEAK_LOCAL = False
STOP = asyncio.Event()
LOOP: asyncio.AbstractEventLoop


def _cors(handler: SimpleHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Cache-Control", "no-store")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIBEOS), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        log.info("http " + fmt, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/state"):
            with STATE_LOCK:
                body = json.dumps(STATE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            _cors(self)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/events"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            _cors(self)
            self.end_headers()
            last = None
            try:
                while True:
                    with STATE_LOCK:
                        payload = json.dumps(STATE)
                    if payload != last:
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last = payload
                    time.sleep(1.0)
            except BrokenPipeError:
                return
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        action = (payload.get("action") or self.path.rsplit("/", 1)[-1]).strip()
        ok = True
        err = None
        try:
            if action in {"push", "speak"}:
                with STATE_LOCK:
                    working = int(STATE.get("working") or 0)
                    ended = int(STATE.get("ended") or 0)
                    attention = int(STATE.get("attention") or 0)
                event = payload.get("event") or "Count update."
                asyncio.run_coroutine_threadsafe(
                    announce(working, ended, attention, event), LOOP
                ).result(25)
            elif action == "find":
                if RADIO is None:
                    ok, err = False, "no local radio (use iPhone bridge)"
                else:
                    asyncio.run_coroutine_threadsafe(RADIO.ping_find(), LOOP).result(8)
            else:
                ok, err = False, f"unknown action {action}"
        except Exception as exc:
            ok, err = False, repr(exc)
        body = json.dumps({"ok": ok, "error": err}).encode("utf-8")
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        _cors(self)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def say_local(text: str) -> None:
    if platform.system() != "Darwin":
        return
    try:
        subprocess.Popen(["say", "-r", "190", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


async def announce(working: int, ended: int, attention: int, event: str | None) -> None:
    line_bits = [
        event or "",
        f"{working} working.",
        f"{ended} ended.",
        f"{attention} need attention.",
    ]
    line = " ".join(b for b in line_bits if b).strip()
    if SPEAK_LOCAL:
        say_local(line)
    if RADIO is not None:
        try:
            await RADIO.speak_counts(working, ended, attention, event)
        except Exception as exc:
            log.warning("radio speak: %s", exc)


def _id_sets(snap: dict) -> dict[str, set[str]]:
    ids = snap.get("ids") or {}
    return {
        "working": set(ids.get("working") or []),
        "ended": set(ids.get("ended") or []),
        "attention": set(ids.get("attention") or []),
    }


def _status_event(prev: dict[str, set[str]] | None, cur: dict[str, set[str]]) -> str | None:
    if prev is None:
        return None
    bits: list[str] = []
    if cur["working"] - prev["working"]:
        bits.append("Started working.")
    if prev["working"] - cur["working"]:
        bits.append("Finished.")
    if cur["attention"] - prev["attention"]:
        bits.append("Needs attention.")
    return " ".join(bits) if bits else None


async def collector_loop(interval: float) -> None:
    last_key = None
    last_ids: dict[str, set[str]] | None = None
    last_push = 0.0
    while not STOP.is_set():
        try:
            snap = snapshot()
            if RADIO is not None:
                snap["watch"] = RADIO.status()
            else:
                snap["watch"] = {"connected": False, "bridge": "iphone"}
            working = int(snap["working"])
            ended = int(snap["ended"])
            attn = int(snap["attention"])
            key = (working, ended, attn)
            ids = _id_sets(snap)
            event = _status_event(last_ids, ids)
            count_changed = last_key is not None and key != last_key
            now = time.time()
            if last_ids is None:
                last_ids = ids
                last_key = key
            elif (event or count_changed) and now - last_push > 2:
                last_key = key
                last_ids = ids
                last_push = now
                snap["event"] = event or "Count update."
                snap["event_ts"] = int(now * 1000)
                try:
                    await announce(working, ended, attn, event or "Count update.")
                except Exception as exc:
                    log.warning("announce: %s", exc)
            else:
                last_ids = ids
                last_key = key
            with STATE_LOCK:
                STATE.clear()
                STATE.update(snap)
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / "snapshot.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except Exception as exc:
            log.exception("collector: %s", exc)
        try:
            await asyncio.wait_for(STOP.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def amain(host: str, port: int, interval: float, use_radio: bool) -> None:
    global LOOP, RADIO
    LOOP = asyncio.get_running_loop()
    if use_radio:
        from ble_watch import WatchRadio

        RADIO = WatchRadio()
    httpd = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("VibeOS API http://%s:%s/  (iPhone polls /api/state)", host, port)
    tasks = [asyncio.create_task(collector_loop(interval), name="collector")]
    if RADIO is not None:
        tasks.append(asyncio.create_task(RADIO.run_forever(STOP), name="radio"))
    try:
        await asyncio.gather(*tasks)
    finally:
        httpd.shutdown()
        if RADIO is not None:
            await RADIO.close()


def main() -> int:
    global SPEAK_LOCAL
    parser = argparse.ArgumentParser(description="VibeOS Mac Mini agent API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7733)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--radio", action="store_true", help="talk to a watch paired to this machine")
    parser.add_argument("--speak-local", action="store_true", help="also speak on this Mac")
    parser.add_argument("--orca-source", default="", help="local or 'Mac Mini'")
    args = parser.parse_args()
    if args.orca_source:
        os.environ["VIBEOS_ORCA_SOURCE"] = args.orca_source
    SPEAK_LOCAL = args.speak_local
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(amain(args.host, args.port, args.interval, args.radio))
    except KeyboardInterrupt:
        STOP.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
