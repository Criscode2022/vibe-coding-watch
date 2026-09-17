"""VibeOS bridge: Orca + Cursor snapshot, BLE watch radio, 240x284 face."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIBEOS = ROOT / "vibeos"
DATA = ROOT / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ble_watch import WatchRadio  # noqa: E402
from collector import snapshot  # noqa: E402

log = logging.getLogger("vibeos")
STATE_LOCK = threading.Lock()
STATE: dict = {"working": 0, "ended": 0, "attention": 0, "watch": {}, "ts": 0}
RADIO: WatchRadio | None = None
STOP = asyncio.Event()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIBEOS), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        log.info("http " + fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/state"):
            with STATE_LOCK:
                body = json.dumps(STATE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
        if RADIO is None:
            ok, err = False, "radio down"
        else:
            try:
                if action == "find":
                    asyncio.run_coroutine_threadsafe(RADIO.ping_find(), LOOP).result(8)
                elif action == "push":
                    title = payload.get("title") or "VibeOS"
                    body = payload.get("body") or "LOOK AT WATCH"
                    with STATE_LOCK:
                        working = int(STATE.get("working") or 0)
                        ended = int(STATE.get("ended") or 0)
                        attention = int(STATE.get("attention") or 0)
                    asyncio.run_coroutine_threadsafe(
                        RADIO.push_message(
                            title,
                            body,
                            alert=True,
                            working=working,
                            ended=ended,
                            attention=attention,
                        ),
                        LOOP,
                    ).result(20)
                else:
                    ok, err = False, f"unknown action {action}"
            except Exception as exc:
                ok, err = False, repr(exc)
        body = json.dumps({"ok": ok, "error": err}).encode("utf-8")
        self.send_response(200 if ok else 500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


LOOP: asyncio.AbstractEventLoop


def windows_toast(title: str, body: str) -> None:
    ps = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(4000, @'
{title}
'@, @'
{body}
'@, [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 4
$n.Dispose()
""".replace("{title}", title.replace("'", "''")).replace("{body}", body.replace("'", "''"))
    try:
        subprocess.Popen(
            [
                r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def watch_text(snap: dict) -> tuple[str, str, bool]:
    working, ended, attn = snap["working"], snap["ended"], snap["attention"]
    title = "VibeOS"
    body = f"{working} work {ended} done {attn} attn"
    return title, body, attn > 0


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


async def collector_loop(radio: WatchRadio, interval: float) -> None:
    last_key = None
    last_ids: dict[str, set[str]] | None = None
    last_push = 0.0
    while not STOP.is_set():
        try:
            snap = snapshot()
            snap["watch"] = radio.status()
            with STATE_LOCK:
                STATE.clear()
                STATE.update(snap)
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA / "snapshot.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
            working = int(snap["working"])
            ended = int(snap["ended"])
            attn = int(snap["attention"])
            key = (working, ended, attn)
            ids = _id_sets(snap)
            now = time.time()
            event = _status_event(last_ids, ids)
            count_changed = last_key is not None and key != last_key
            if last_ids is None:
                last_ids = ids
                last_key = key
            elif radio.connected and (event or count_changed) and now - last_push > 3:
                title, body, _alert = watch_text(snap)
                last_key = key
                last_ids = ids
                last_push = now
                windows_toast(title, body)
                try:
                    await radio.push_message(
                        title,
                        body,
                        alert=True,
                        working=working,
                        ended=ended,
                        attention=attn,
                        event=event or "Count update.",
                    )
                except Exception as exc:
                    log.warning("push failed: %s", exc)
            else:
                last_ids = ids
                last_key = key
        except Exception as exc:
            log.exception("collector: %s", exc)
        try:
            await asyncio.wait_for(STOP.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


def open_face(port: int) -> None:
    url = f"http://127.0.0.1:{port}/"
    edge = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
    if not edge.exists():
        edge = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe"
    args = [
        str(edge),
        f"--app={url}",
        "--window-size=280,360",
        "--window-position=40,40",
    ]
    if edge.exists():
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


async def amain(port: int, interval: float, open_ui: bool) -> None:
    global LOOP, RADIO
    LOOP = asyncio.get_running_loop()
    radio = WatchRadio()
    RADIO = radio
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    log.info("VibeOS face http://127.0.0.1:%s/", port)
    if open_ui:
        open_face(port)
    tasks = [
        asyncio.create_task(radio.run_forever(STOP), name="radio"),
        asyncio.create_task(collector_loop(radio, interval), name="collector"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        httpd.shutdown()
        await radio.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="VibeOS watch bridge")
    parser.add_argument("--port", type=int, default=7733)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(amain(args.port, args.interval, not args.no_browser))
    except KeyboardInterrupt:
        STOP.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
