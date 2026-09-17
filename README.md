# VibeOS — coding watch for the ZTE Watch Live 3

Mac Mini counts Orca agents. iPhone is the Bluetooth bridge to the watch, so counts speak on your wrist anywhere the phone and watch are paired.

```
Orca on Mac Mini  →  VibeOS daemon :7733  →  iPhone (Tailscale)  →  ZTE Live 3 speaker
```

## What the watch says

When a Mac Mini Orca agent **starts**, **finishes**, or **needs attention**:

> Started working. 1 working. 5 ended. 0 need attention.

## 1. Always-on Mac Mini

Needs `orca` on the PATH (Orca app / CLI). Then:

```bash
git clone git@github.com:Criscode2022/vibe-coding-watch.git ~/GitHub/vibe-coding-watch
cd ~/GitHub/vibe-coding-watch
chmod +x macos/install-mac.sh
./macos/install-mac.sh
```

That installs a LaunchAgent (`com.vibeos.bridge`) which keeps `http://0.0.0.0:7733/` up after reboot. Check:

```bash
curl -s http://127.0.0.1:7733/api/state | python3 -m json.tool
```

Leave Tailscale running on the Mini. Note the Mini’s Tailscale IP (example used in the iPhone app: `http://100.118.53.14:7733`).

## 2. iPhone as watch bridge

1. Pair the **ZTE WATCH Live3** to the iPhone as a Bluetooth headset (Settings → Bluetooth). Quit **Z Sports** so it does not steal the radio.
2. Install Tailscale on the iPhone and join the same tailnet as the Mini.
3. On the Mac Mini, open `ios/VibeOS/VibeOS.xcodeproj` in Xcode, set your Team, plug in the iPhone, Run.
4. In VibeOS, set **Mac Mini Tailscale URL** to `http://<mini-tailscale-ip>:7733` and tap **Save URL**.
5. Keep VibeOS open (or in the background). It polls `/api/state` and speaks counts through the watch Hands-Free speaker.

**Speak counts** in the app repeats the current totals.

## Agent counts (Mac Mini only)

| Row | Meaning |
| --- | --- |
| working | Orca agent currently in a turn |
| ended | idle / `done` agent |
| attention | unread finished work or a wait/block |

Windows Orca tabs are ignored.

## Optional: watch paired to a computer

```bash
python3 bridge/server.py --radio --speak-local
```

That talks BLE/HFP from the machine itself instead of the iPhone.
