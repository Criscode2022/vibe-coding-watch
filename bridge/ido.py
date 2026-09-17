"""IDO/Realtek command protocol on ZTE Live 3's 0x27F0 service (0x0AF0 clone)."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable


WRITE_CMD = "000027f6-0000-1000-8000-00805f9b34fb"
NOTIFY_CMD = "000027f7-0000-1000-8000-00805f9b34fb"
WRITE_BULK = "000027f1-0000-1000-8000-00805f9b34fb"
NOTIFY_BULK = "000027f2-0000-1000-8000-00805f9b34fb"

CMD_GET = 0x02
CMD_SET = 0x03
CMD_BIND = 0x04
CMD_MSG = 0x05
CMD_APP = 0x06

KEY_GET_INFO = 0x01
KEY_GET_BATT = 0x05
KEY_SET_TIME = 0x01
KEY_MSG_CALL = 0x01
KEY_MSG_STOP = 0x02
KEY_MSG_MSG = 0x03
KEY_FIND = 0x04

# IDO message type byte (watch icon)
TYPE_SMS = 1
TYPE_MAIL = 2
TYPE_WECHAT = 3
TYPE_WHATSAPP = 8
TYPE_CALENDAR = 12


def get_device_info() -> bytes:
    return bytes([CMD_GET, KEY_GET_INFO])


def get_battery() -> bytes:
    return bytes([CMD_GET, KEY_GET_BATT])


def set_time(when: datetime | None = None) -> bytes:
    now = when or datetime.now()
    year = now.year
    # Saturday=6 in VeryFit dumps → Sunday=0
    week = (now.weekday() + 1) % 7
    payload = bytes(
        [
            CMD_SET,
            KEY_SET_TIME,
            year & 0xFF,
            (year >> 8) & 0xFF,
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second,
            week,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )
    return payload


def find_watch() -> bytes:
    return bytes([CMD_APP, KEY_FIND, 0x00])


def open_ancs() -> bytes:
    return bytes([CMD_APP, 0x30])


def get_notice_status() -> bytes:
    return bytes([CMD_GET, 0x10])


def get_func_table() -> bytes:
    return bytes([CMD_GET, 0x02])


def enable_notice() -> list[bytes]:
    veryfit = bytes([CMD_SET, 0x30, 0x88, 0x00, 0x00, 0xAA]) + bytes(14)
    legacy = bytes([CMD_SET, 0x30, 0x01, 0x00, 0x00, 0x01, 0x03])
    return [veryfit, legacy]


def raise_to_wake() -> bytes:
    return bytes([CMD_SET, 0x28, 0xAA, 0x05, 0x01, 0x00, 0x00, 0x17, 0x3B])


def dnd_off() -> bytes:
    return bytes([CMD_SET, 0x29, 0x55, 0x17, 0x00, 0x07, 0x00, 0x02, 0xFE, 0x55, 0x17, 0x00, 0x07, 0x00, 0x00, 0x00])


def bind_start() -> bytes:
    return bytes([CMD_BIND, 0x01, 0xF1, 0x01, 0x01, 0x02, 0x02, 0x01, 0x00])


def weather_on() -> bytes:
    return bytes([CMD_SET, 0x2D, 0xAA, 0x00, 0x00, 0x00])


def weather_data(working: int, ended: int, attention: int) -> bytes:
    w = max(0, min(99, working))
    e = max(0, min(99, ended))
    a = max(0, min(99, attention))
    # today_type, tmp, max, min, humidity, uv, aqi + 3 forecast triples
    return bytes([0x0A, 0x01, 0x01, w, e, a, 50, 0, 0, 0x01, e, a, 0x01, w, a, 0x01, w, e])


def weather_city(name: str = "VIBEOS") -> bytes:
    raw = name.encode("utf-8")[:16]
    return bytes([0x0A, 0x02, len(raw)]) + raw + bytes(max(0, 17 - len(raw)))


def encode_miband(text: str) -> bytes:
    return bytes([CMD_MSG, KEY_MSG_CALL]) + (text or "VibeOS").encode("utf-8")[:18]


def _chunks(buf: bytes, size: int = 16) -> Iterable[bytes]:
    if not buf:
        yield b"\x00" * size
        return
    for i in range(0, len(buf), size):
        piece = buf[i : i + size]
        if len(piece) < size:
            piece = piece + b"\x00" * (size - len(piece))
        yield piece


def _utf8_clip(text: str, max_chars: int = 20) -> bytes:
    raw = (text or "").encode("utf-8")
    if len(raw) <= max_chars:
        return raw
    raw = raw[:max_chars]
    while raw and (raw[-1] & 0xC0) == 0x80:
        raw = raw[:-1]
    return raw


def encode_message(title: str, body: str, kind: int = TYPE_SMS) -> list[bytes]:
    title_b = _utf8_clip(title, 20)
    body_b = _utf8_clip(body, 20)
    phone_b = b""
    payload = bytes([kind, len(body_b), len(phone_b), len(title_b)]) + phone_b + title_b + body_b
    pieces = list(_chunks(payload, 16))
    total = len(pieces)
    frames = []
    for idx, piece in enumerate(pieces, start=1):
        frames.append(bytes([CMD_MSG, KEY_MSG_MSG, total, idx]) + piece)
    return frames


def encode_call(name: str, number: str = "") -> list[bytes]:
    name_b = _utf8_clip(name, 20)
    phone_b = _utf8_clip(number, 20)
    payload = bytes([len(phone_b), len(name_b)]) + phone_b + name_b
    pieces = list(_chunks(payload, 16))
    total = len(pieces)
    frames = []
    for idx, piece in enumerate(pieces, start=1):
        frames.append(bytes([CMD_MSG, KEY_MSG_CALL, total, idx]) + piece)
    return frames


def stop_call() -> bytes:
    return bytes([CMD_MSG, KEY_MSG_STOP, 0x01])
