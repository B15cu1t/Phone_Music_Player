# ● biscuit music player

Ad-free, account-aware music streaming for Android via Termux.
No YouTube app. No ads. No Spotify. Just your music.

---

## What it does

- Streams audio-only from YouTube / YouTube Music (no video = way faster)
- Auto-builds an infinite queue from your liked songs, watch history, and recommendations
- Keeps playing when your screen is off
- Car-friendly web UI: big buttons, orange & black, works one-handed
- Search from any device on your network

---

## Install & Run

### 1 — Install Termux

Get Termux from **F-Droid** (not the Play Store version, it's outdated): https://f-droid.org/packages/com.termux/

Also install **Termux:API** from F-Droid (needed for wake lock): https://f-droid.org/packages/com.termux.api/

### 2 — Open Termux and run:

```
pkg update -y
pkg install python mpv git termux-api -y
```

### 3 — Clone the project

```
git clone https://github.com/B15cu1t/Phone_Music_Player
cd Phone_Music_Player
```

### 4 — Run setup (first time only)

```
python setup.py
```

This will:
- Install Python deps (flask, yt-dlp, ytmusicapi)
- Walk you through YouTube Music login (OAuth — opens a browser link)
- Save your credentials to `oauth.json`

> **Without login**: the player still works using YouTube search,
> but won't have your liked songs or personal recommendations.

### 5 — Start the player

```
python server.py
```

Then open **http://127.0.0.1:5000** in your phone browser.

### Make it an "app" (Add to Home Screen)

- Chrome/Firefox: tap the three-dot menu → "Add to Home Screen"
- It'll show as a full-screen app with no browser chrome

---

## Use from your car

1. Connect phone to car via Bluetooth or aux
2. Open the Biscuit app (home screen shortcut)
3. Tap play — queue builds automatically
4. Lock your screen — music keeps playing (wake lock is active)
5. Use Bluetooth media buttons to skip tracks

The UI is designed for one-handed use: big tap targets, high contrast.

---

## Keep it running in the background

Termux may get killed by Android battery optimization. Fix this once:

- **Settings → Apps → Termux → Battery → Unrestricted**
- Or: Settings → Battery → Background app management → Termux → Don't restrict

Also works via adb:

```
adb shell dumpsys deviceidle whitelist +com.termux
```

---

## Access from other devices on your network

The server binds to `0.0.0.0:5000` by default, so any device on your Wi-Fi can open it:

```
http://<your-phone-ip>:5000
```

Find your phone's IP: Settings → Wi-Fi → tap your network → IP address.

---

## File structure

```
Phone_Music_Player/
├── server.py          main Flask app + playback logic
├── setup.py           first-time setup + YTMusic login
├── requirements.txt   Python deps
├── oauth.json         YTMusic credentials (created by setup.py)
└── templates/
    └── index.html     Biscuit UI
```

---

## Troubleshooting

**Music won't start / buffers a lot**
yt-dlp resolves a fresh stream URL each time. If it's slow, try: `pip install -U yt-dlp`

**"mpv not found"**
```
pkg install mpv
```

**YTMusic auth expired**
```
python setup.py
```

**Termux killed when screen off**
See "Keep it running in the background" above.

**Port 5000 already in use**
Edit `server.py`, last line: change `port=5000` to `port=5001`, then open `http://127.0.0.1:5001`.

---

## How the auto-queue works

1. On start, fetches your **liked songs** + **watch history** from YTMusic
2. Seeds a **radio** playlist from the current track
3. Shuffles and deduplicates into a 40-track queue
4. As you near the end, it **automatically refills** using the current song as seed
5. You never run out — it's infinite radio personalized to your taste

---

Built with: Python · Flask · yt-dlp · ytmusicapi · mpv
