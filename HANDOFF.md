# VibeOS agent handoff

Read this before changing anything. It is the working memory for the next agent.

Repo: https://github.com/Criscode2022/vibe-coding-watch  
Default branch: `main`  
Local clone used in the original session: `C:\Users\crist\GitHub\vibe-coding-watch`  
GitHub account: `Criscode2022` (SSH).

The user (Cristian) wants a **vibe coding watch**: a ZTE Watch Live 3 that, over Bluetooth, reports how many Orca agents are **working**, **ended**, and **need attention**. Cursor was an early extra; current product scope is **Mac Mini Orca agents only**. Spoken counts on the watch speaker are the output that actually worked. The user does **not** want beeps.

---

## Goal (user intent)

1. Wrist audio of agent counts, in real time, when an agent starts a turn, finishes, or needs attention.
2. Detect **only Mac Mini** Orca agents (ignore Windows Orca tabs).
3. Daemon **always running on the Mac Mini**.
4. **iPhone as the Bluetooth bridge** to the watch so it works away from the PC: Mini → Tailscale → iPhone → watch Hands-Free speaker.

A custom OS was requested first. That is **not possible** on this hardware. Do not try to flash firmware over Bluetooth.

---

## Hardware (do not re-discover from scratch)

| Item | Value |
| --- | --- |
| Watch | ZTE Watch Live 3, model **SW2301** |
| Companion app (vendor) | **Z Sports** (`com.zte.sports.abroad`), Android/iOS. Not Wear OS. |
| Screen | 1.83" IPS, **240×284** |
| Classic BT name | `ZTE WATCH Live3-BT_B441` |
| Classic MAC | `41:42:F9:70:B4:41` (paired to Windows as Hands-Free + HID) |
| BLE name | `ZTE WATCH Live3_B441` |
| BLE MAC | `41:42:C6:70:B4:41` |
| Advertised service | `000027f0-0000-1000-8000-00805f9b34fb` |
| PnP VID/PID | Apple VID spoof `VID_05AC` `PID_0220` (cheap-watch Hands-Free trick) |
| Windows audio device | `Headset (ZTE WATCH Live3-BT_B441 Hands-Free)` |

This is a locked Realtek/IDO RTOS fitness watch. No ADB, no fastboot, no public ROM. Charge pins are not USB data. Flashing a custom OS over the headset link will not work and can brick it.

**Orca Mac Mini** (from this session):

- Orca environment name: **`Mac Mini`**
- Environment id: `9417d4a8-3948-41d3-ac91-ae960fd11ebf`
- Tailscale / paired endpoint seen: `ws://100.118.53.14:6768`
- iPhone default bridge URL in the app: `http://100.118.53.14:7733` (update if Tailscale IP changes)

---

## What actually works (proven)

Spoken counts through the **Hands-Free speaker** work. On Windows this was `winmm.waveOut` to the ZTE headset device, 8 kHz mono PCM, after SAPI (`System.Speech`) wrote a WAV. The user heard “Vibe OS. N working. N ended. N need attention.”

IDO BLE from Windows also connected:

- GATT service `0x27F0` is an IDO/VeryFit clone of `0x0AF0` (`0x27F6` write, `0x27F7` notify, `0x27F1`/`0x27F2` bulk).
- `GET 0x02 0x01` (info), `0x02 0x05` (battery), `SET 0x03 0x01` (time) ACK.
- Incoming-call packets `05 01` ACK. SMS `05 03` does **not** ACK and does not show.
- The watch did **not** show a visible custom UI. Do not depend on IDO notifications for the product. Audio is the product.

Beeps were added then removed at the user’s request. Do not bring beeps back.

---

## Architecture (current target)

```
Orca CLI on Mac Mini
        │  worktree ps --json + terminal list --json
        ▼
VibeOS daemon  (Python, launchd, 0.0.0.0:7733)
        │  GET /api/state  JSON
        ▼
iPhone VibeOS app  (Tailscale)
        │  AVSpeechSynthesizer, AVAudioSession allowBluetooth
        ▼
ZTE Live 3 Hands-Free speaker
```

Windows is no longer the intended radio host. `start.ps1` still exists and forces `--orca-source "Mac Mini"` if someone runs the API from Windows.

On **Darwin** the collector uses local `orca` (the Mini *is* the host).  
On **Windows** it uses `orca --environment "Mac Mini"`.  
Override: env `VIBEOS_ORCA_SOURCE` or `--orca-source`.

Cursor collection is disabled in `snapshot()` (empty stub). Do not mix Cursor into counts unless the user asks again.

---

## Repo map

| Path | Role |
| --- | --- |
| `bridge/collector.py` | Orca agent classification (Mini only) |
| `bridge/server.py` | HTTP API `:7733`, SSE `/api/events`, optional `--radio` / `--speak-local` |
| `bridge/ble_watch.py` | Windows/Mac BLE IDO session (optional `--radio`) |
| `bridge/ido.py` | IDO packet builders |
| `bridge/speaker.py` | Windows SAPI → 8 kHz PCM → ZTE `waveOut` |
| `bridge/probe_ble.py` | One-shot BLE GATT dump |
| `bridge/test_notify.py` | One-shot connect + find + message |
| `vibeos/` | 240×284 companion face (`http://host:7733/`) |
| `macos/install-mac.sh` | venv + LaunchAgent `com.vibeos.bridge` |
| `macos/com.vibeos.bridge.plist` | Template; `VIBEOS_ROOT` / `VIBEOS_PYTHON` replaced at install |
| `ios/VibeOS/` | Xcode iOS 17 app, bundle id `com.criscode.vibeos` |
| `README.md` | Short user setup |
| `HANDOFF.md` | This file |

Python 3.14 was used on Windows. Dependency: `bleak` (only needed for `--radio`).

---

## Agent detection (do not regress)

**Source of truth on Mac Mini:** `orca worktree ps --json` → each worktree’s `agents[]`:

```json
{
  "paneKey": "<tabId>:<leafId>",
  "state": "done" | "working" | ...,
  "agentType": "grok" | "claude" | ...,
  "prompt": "...",
  "interrupted": false
}
```

Map:

| Condition | Count |
| --- | --- |
| `state` in working/running/thinking/streaming/in-progress/tool/active | **working** |
| `state` in waiting/ask/blocked/error/failed, or `interrupted` | **attention** |
| `unread: true` **and** state is done/completed/idle | **attention** |
| `state` in done/completed/idle/stopped/exited | **ended** |

**Fallback** for Grok TUI panes with `agentIdentity` but empty `agents[]` (common on Windows; also some Mini terminals): `orca terminal list --json`.

Do **not** count a connected Grok tab as working just because it exists. Idle TUI (`[stable]`, `Resume session`, empty `> ` / `❯` prompt, “Turn completed”) is **ended**. Shell prompts (`user@host %`) with `agentIdentity` should be skipped unless they look like the Grok TUI.

Dedup: if a terminal’s `tabId:leafId` matches a structured `paneKey`, skip the terminal row.

Stable ids: `"{host}:{paneKey or handle}"`. Status changes must **move the same id** between working/ended/attention sets so the watch can say “Started working” / “Finished” / “Needs attention”. Do not put the title or preview in the id.

Do **not** count worktrees themselves as agents. Do **not** call `orca orchestration task-list` without `--from` (it errors). `worker-list` was empty in this session.

First snapshot is a **baseline** (no speech). Later diffs of id sets trigger speech.

---

## HTTP API

Bind: `0.0.0.0:7733` (LaunchAgent). CORS `*`.

| Method | Path | |
| --- | --- | --- |
| GET | `/api/state` | Current JSON snapshot |
| GET | `/api/events` | SSE, `data: <same JSON>` on change |
| GET | `/` | 240×284 face |
| POST | `/api/push` or `/api/speak` | Speak current counts (local radio/`say` if enabled) |
| POST | `/api/find` | IDO find; fails with `--no-radio` (default) |

Snapshot shape (fields the iPhone decoder expects):

```json
{
  "ts": 0,
  "source": "local" | "Mac Mini",
  "working": 0,
  "ended": 0,
  "attention": 0,
  "event": "Started working." | null,
  "ids": { "working": ["Mac Mini:..."], "ended": [], "attention": [] },
  "orca": { "items": { "working": [], "ended": [], "attention": [] } },
  "watch": { "connected": false, "bridge": "iphone" }
}
```

Default Mini daemon does **not** open BLE (`--radio` is off). iPhone speaks. `--speak-local` uses macOS `say` for debugging without the phone.

---

## How to run

### Mac Mini (intended production)

Needs `orca` on `PATH`.

```bash
git clone git@github.com:Criscode2022/vibe-coding-watch.git ~/GitHub/vibe-coding-watch
cd ~/GitHub/vibe-coding-watch
git pull
chmod +x macos/install-mac.sh
./macos/install-mac.sh
curl -s http://127.0.0.1:7733/api/state
```

LaunchAgent label: `com.vibeos.bridge`  
Logs: `data/vibeos.log`, `data/vibeos.err`  
Reload: `launchctl kickstart -k gui/$UID/com.vibeos.bridge`

Keep **Tailscale** up. If `100.118.53.14` is stale, put the new Tailscale IP in the iPhone app.

**This install has not been executed on the Mini in the original session.** The Windows machine ran the collector via `orca --environment "Mac Mini"` instead.

### iPhone

1. Unpair the watch from Windows if it is still the Hands-Free device there.
2. iPhone Settings → Bluetooth → pair **ZTE WATCH Live3** as a headset. Force-quit **Z Sports**.
3. Tailscale on the phone, same tailnet.
4. On the Mini, open `ios/VibeOS/VibeOS.xcodeproj`, set a Development Team (`DEVELOPMENT_TEAM` is empty in the pbxproj), Run on a physical iPhone (iOS 17+).
5. Set URL `http://<mini-tailscale-ip>:7733`, Save URL, keep the app in foreground or background (audio + bluetooth-central modes are in Info.plist).

Speech uses `AVAudioSession` `.playback` + `.allowBluetooth` so HFP SCO can take the utterance. That is the same idea as the Windows Hands-Free `waveOut` path.

The Xcode project was authored on Windows and has not been built in this session. First open may need a team, bundle id uniqueness, and ATS is already `NSAllowsArbitraryLoads` for the Tailscale HTTP URL.

### Windows leftover

```powershell
cd $env:USERPROFILE\GitHub\vibe-coding-watch
.\start.ps1
```

Collects Mini via `orca --environment "Mac Mini"`. Does not enable `--radio` unless you pass it. Face: `http://127.0.0.1:7733/`.

---

## IDO notes (only if you revive `--radio`)

UUIDs in `bridge/ido.py`. Protocol family: Gadgetbridge ID115 / VeryFit / d3nd3 idowatch `0x0AF0`, shifted to `0x27xx`.

Safe: GET info/battery, SET time, MSG call `05 01`, find `06 04` (this firmware answered `06 02` — camera-to-phone — find may not vibrate).  
Do **not** send factory reset `03 27`, reboot `F0 01`, unbind, or OTA on `0x2760`.  
`SET 0x30` notice enable ACKed `03 30 00` (not the VeryFit `03 30 88 01` shape). Visible SMS still did not appear.

Func table from this watch (`02 02`): call bits include incoming; msg bit looked SMS-only. Battery was ~36–46% during tests.

---

## Known gaps / next work

- **Mac Mini LaunchAgent not installed yet.** Do that on the Mini before relying on “always on”.
- **iOS app not built/signed yet.** Needs a local Xcode team and a device run.
- **Background iOS:** polling every 2s while the app is killed will stop. Audio background helps while speaking; a Live Activity / BGTask may be needed for “anywhere all day”.
- **Tailscale IP is hardcoded** as default `http://100.118.53.14:7733`. Prefer MagicDNS if the tailnet has a stable name; make the URL the first-run setup.
- **iPhone does not implement IDO BLE**, only HFP speech. Enough for the proven UX. BLE can be ported from `ido.py` later if a visible watch alert is required.
- **Z Sports vs VibeOS:** they fight over BLE. User must not leave Z Sports connected if the iPhone app owns the watch.
- **`install-mac.sh` plist substitution** uses a Python heredoc; confirm paths after first install.
- Collector still contains unused Cursor helpers; `snapshot()` does not call them.
- `bridge/server.py` `LOOP` is set in `amain`; POST before the loop starts would fail (same as before).
- Windows `CREATE_NO_WINDOW` is gated on `os.name == "nt"` so Mac is fine.

---

## User preferences captured

- Spoken **counts**, not beeps.
- Only **Mac Mini** agents.
- Always-on Mini + **iPhone Bluetooth bridge**.
- Original ask for a custom watch OS is closed: hardware cannot take one over BT.

---

## Suggested first commands for the next agent

```bash
# On Mac Mini
cd ~/GitHub/vibe-coding-watch && git pull
./macos/install-mac.sh
curl -s http://127.0.0.1:7733/api/state | python3 -m json.tool

# Confirm only Mini agents appear (working/ended/attention)
# Then open ios/VibeOS/VibeOS.xcodeproj, run on iPhone, pair watch as headset
```

If counts look wrong again: dump `orca worktree ps --json` and `orca terminal list --json` **on the Mini** (or `orca --environment "Mac Mini" ...` from Windows) and compare `agents[].state` vs idle TUI previews. Do not go back to “every connected grok tab is working”.
