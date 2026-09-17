# VibeOS — coding watch for the ZTE Watch Live 3

The Live 3 (SW2301) is a locked Realtek/IDO fitness watch, not Wear OS. It has no ADB, no fastboot, and no public firmware. A custom kernel cannot be flashed over Bluetooth.

VibeOS is the layer that can run: a 240×284 companion face plus a Windows bridge that talks to the watch over BLE (`GATT 0x27F0`) and speaks agent counts through the Hands-Free speaker.

## Wrist audio

When an Orca or Cursor agent **starts working**, **finishes**, or **needs attention**, the watch speaks the counts, for example:

> Started working. Vibe OS. 1 working. 0 ended. 0 need attention.

Manual **push now** on the face repeats the current counts. Keep the watch paired to this PC (Hands-Free + BLE). Pairing it back to a phone in ZSports drops the speaker.

## Face rows

| Row | Source |
| --- | --- |
| working | live Orca agent terminals + recent Cursor agents |
| ended | completed Orca worktrees + idle Cursor transcripts |
| attention | unread / blocked Orca cards, Cursor errors |

## Run

```powershell
cd $env:USERPROFILE\GitHub\vibe-coding-watch
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.ps1
```

Face: `http://127.0.0.1:7733/`
