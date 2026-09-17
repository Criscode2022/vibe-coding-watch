"""Play a beep on the Live 3 Hands-Free speaker (Windows audio endpoint)."""

from __future__ import annotations

import array
import ctypes
import logging
import math
import struct
import subprocess
import threading
import time
import wave
from ctypes import wintypes
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

log = logging.getLogger("vibeos.speaker")
winmm = ctypes.windll.winmm


class WAVEOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", wintypes.DWORD),
        ("wChannels", wintypes.WORD),
        ("wReserved1", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_void_p),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
    ]


def _device_index() -> int | None:
    n = winmm.waveOutGetNumDevs()
    for i in range(n):
        caps = WAVEOUTCAPSW()
        winmm.waveOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
        name = caps.szPname or ""
        if any(token in name for token in ("ZTE", "Live3", "B441", "WATCH")):
            log.info("speaker device %s %s", i, name)
            return i
    return None


def _beep(seconds: float = 1.4, hz: float = 880.0) -> bool:
    dev = _device_index()
    if dev is None:
        log.warning("no ZTE waveOut device")
        return False
    rate = 8000
    samples = int(rate * seconds)
    chunks = []
    for n in range(samples):
        env = 1.0
        if n < 400:
            env = n / 400
        if n > samples - 400:
            env = max(0.0, (samples - n) / 400)
        v = int(18000 * env * math.sin(2 * math.pi * hz * n / rate))
        chunks.append(struct.pack("<h", v))
    pcm = b"".join(chunks)
    fmt = WAVEFORMATEX(1, 1, rate, rate * 2, 2, 16, 0)
    handle = wintypes.HANDLE()
    err = winmm.waveOutOpen(ctypes.byref(handle), dev, ctypes.byref(fmt), 0, 0, 0)
    if err:
        log.warning("waveOutOpen %s", err)
        return False
    buf = ctypes.create_string_buffer(pcm)
    hdr = WAVEHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
    hdr.dwBufferLength = len(pcm)
    winmm.waveOutPrepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveOutWrite(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
    time.sleep(seconds + 0.3)
    winmm.waveOutReset(handle)
    winmm.waveOutUnprepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveOutClose(handle)
    return True


def _status_line(working: int, ended: int, attention: int) -> str:
    def part(n: int, one: str, many: str) -> str:
        return f"1 {one}" if n == 1 else f"{n} {many}"

    bits = [
        part(working, "working", "working"),
        part(ended, "ended", "ended"),
        part(attention, "needs attention", "need attention"),
    ]
    if attention:
        return "Attention. " + ". ".join(bits) + "."
    return "Vibe OS. " + ". ".join(bits) + "."


def _synth_wav(text: str, wav_path: Path) -> bool:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path = wav_path.with_suffix(".txt")
    txt_path.write_text(text, encoding="utf-8")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.Rate = 2; $s.Volume = 100; "
        f"$s.SetOutputToWaveFile('{str(wav_path).replace(chr(39), chr(39)+chr(39))}'); "
        f"$s.Speak([IO.File]::ReadAllText('{str(txt_path).replace(chr(39), chr(39)+chr(39))}')); "
        "$s.Dispose();"
    )
    try:
        proc = subprocess.run(
            [
                r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps,
            ],
            timeout=20,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("sapi: %s", exc)
        return False
    if proc.returncode != 0 or not wav_path.exists():
        log.warning("sapi failed rc=%s %s", proc.returncode, proc.stderr[-200:] if proc.stderr else "")
        return False
    return True


def _pcm8k_from_wav(path: Path) -> bytes | None:
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if sw != 2:
        log.warning("wav sampwidth %s", sw)
        return None
    samples = array.array("h")
    samples.frombytes(frames)
    if ch == 2:
        mixed = array.array("h")
        for i in range(0, len(samples) - 1, 2):
            mixed.append(int((samples[i] + samples[i + 1]) / 2))
        samples = mixed
    if rate != 8000 and rate > 0:
        out = array.array("h")
        n = max(1, int(len(samples) * 8000 / rate))
        for i in range(n):
            src = min(len(samples) - 1, int(i * rate / 8000))
            out.append(samples[src])
        samples = out
    return samples.tobytes()


def _play_pcm8k(pcm: bytes) -> bool:
    dev = _device_index()
    if dev is None:
        return False
    seconds = max(0.2, len(pcm) / (8000 * 2))
    fmt = WAVEFORMATEX(1, 1, 8000, 16000, 2, 16, 0)
    handle = wintypes.HANDLE()
    err = winmm.waveOutOpen(ctypes.byref(handle), dev, ctypes.byref(fmt), 0, 0, 0)
    if err:
        log.warning("waveOutOpen %s", err)
        return False
    buf = ctypes.create_string_buffer(pcm)
    hdr = WAVEHDR()
    hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
    hdr.dwBufferLength = len(pcm)
    winmm.waveOutPrepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveOutWrite(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
    time.sleep(seconds + 0.4)
    winmm.waveOutReset(handle)
    winmm.waveOutUnprepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
    winmm.waveOutClose(handle)
    return True


_SPEAK_LOCK = threading.Lock()


def announce_counts(
    working: int,
    ended: int,
    attention: int,
    event: str | None = None,
) -> bool:
    line = _status_line(working, ended, attention)
    if event:
        line = f"{event} {line}"
    log.info("speak %s", line)
    wav = DATA / "announce.wav"
    with _SPEAK_LOCK:
        if not _synth_wav(line, wav):
            return False
        pcm = _pcm8k_from_wav(wav)
        if not pcm:
            return False
        return _play_pcm8k(pcm)
