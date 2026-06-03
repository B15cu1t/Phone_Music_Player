#!/usr/bin/env python3
"""
Biscuit Music Player - server.py
Fixed: proper mpv IPC socket for pause/resume, one process at a time,
no auto-start on launch (wait for user to press play), remove from queue.
"""

import os, json, random, threading, subprocess, time, logging, socket, tempfile
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

try:
    from ytmusicapi import YTMusic
    YTM_AVAILABLE = True
except ImportError:
    YTM_AVAILABLE = False

import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("biscuit")

app = Flask(__name__, template_folder="templates", static_folder="static")

# ═══════════════════════════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════════════════════════

state = {
    "playing":     False,
    "current":     None,
    "queue":       [],
    "queue_index": 0,
    "volume":      80,
    "progress":    0,
    "shuffle":     True,
    "repeat":      False,
    "error":       None,
    "loading":     False,   # true while resolving URL
}

# one lock to rule them all — prevents double-play
play_lock    = threading.Lock()
player_proc  = None
ipc_socket   = None   # path to mpv IPC socket
is_paused    = False
play_serial  = 0      # increment each play_track call; watcher checks it hasn't changed

ytm = None
AUTH_FILE = Path("oauth.json")

# ═══════════════════════════════════════════════════════════════════════════
# MPV IPC — send commands to running mpv
# ═══════════════════════════════════════════════════════════════════════════

def mpv_cmd(cmd: dict) -> bool:
    """Send a JSON command to mpv via IPC socket. Returns True on success."""
    global ipc_socket
    if not ipc_socket or not Path(ipc_socket).exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(ipc_socket)
        s.sendall((json.dumps(cmd) + "\n").encode())
        s.close()
        return True
    except Exception as e:
        log.debug(f"mpv_cmd failed: {e}")
        return False

def mpv_set_pause(paused: bool):
    return mpv_cmd({"command": ["set_property", "pause", paused]})

def mpv_set_volume(vol: int):
    return mpv_cmd({"command": ["set_property", "volume", vol]})

def mpv_get_pos() -> float:
    """Get current playback position in seconds."""
    global ipc_socket
    if not ipc_socket or not Path(ipc_socket).exists():
        return 0.0
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(ipc_socket)
        s.sendall((json.dumps({"command": ["get_property", "time-pos"]}) + "\n").encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        s.close()
        resp = json.loads(data.decode().strip().split("\n")[0])
        return float(resp.get("data", 0) or 0)
    except Exception:
        return 0.0

# ═══════════════════════════════════════════════════════════════════════════
# YTMUSIC
# ═══════════════════════════════════════════════════════════════════════════

def init_ytmusic():
    global ytm
    if not YTM_AVAILABLE:
        return
    for candidate in ["browser.json", "oauth.json"]:
        p = Path(candidate)
        if p.exists():
            try:
                ytm = YTMusic(str(p))
                log.info(f"YTMusic authenticated via {candidate}")
                return
            except Exception as e:
                log.error(f"Auth failed ({candidate}): {e}")
    log.warning("No auth file — unauthenticated mode")

def fetch_liked_songs(limit=100):
    if ytm is None: return []
    try:
        liked = ytm.get_liked_songs(limit=limit)
        return [_t(t) for t in liked.get("tracks", []) if t.get("videoId")]
    except Exception as e:
        log.error(f"liked: {e}"); return []

def fetch_history(limit=50):
    if ytm is None: return []
    try:
        return [_t(t) for t in ytm.get_history()[:limit] if t.get("videoId")]
    except Exception as e:
        log.error(f"history: {e}"); return []

def fetch_recommendations(video_id, limit=20):
    if ytm is None: return []
    try:
        radio = ytm.get_watch_playlist(videoId=video_id, radio=True, limit=limit)
        return [_t(t) for t in radio.get("tracks", []) if t.get("videoId")]
    except Exception as e:
        log.error(f"recs: {e}"); return []

def search_tracks(query, limit=10):
    if ytm is not None:
        try:
            results = ytm.search(query, filter="songs", limit=limit)
            tracks = [_t(t) for t in results if t.get("videoId")]
            if tracks: return tracks
        except Exception as e:
            log.error(f"search: {e}")
    return _ytdlp_search(query, limit)

def _ytdlp_search(query, limit=10):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        return [{
            "video_id":  e.get("id",""),
            "title":     e.get("title","Unknown"),
            "artist":    e.get("uploader","Unknown Artist"),
            "thumbnail": e.get("thumbnail",""),
            "duration":  e.get("duration",0),
        } for e in info.get("entries",[]) if e]
    except Exception as e:
        log.error(f"ytdlp search: {e}"); return []

def _t(t):
    artists = ", ".join(a["name"] for a in t.get("artists", []))
    return {
        "video_id":  t.get("videoId",""),
        "title":     t.get("title","Unknown"),
        "artist":    artists or t.get("author","Unknown Artist"),
        "thumbnail": _best_thumb(t.get("thumbnails",[])),
        "duration":  t.get("duration_seconds", t.get("duration", 0)),
    }

def _best_thumb(thumbs):
    if not thumbs: return ""
    return max(thumbs, key=lambda t: t.get("width",0), default=thumbs[0]).get("url","")

def seed_queue_from_track(track, size=30):
    """
    Build a queue of similar songs based on a track dict.
    Uses the artist + title to search for related music — no auth needed.
    """
    artist = track.get("artist", "")
    title  = track.get("title", "")

    # strip junk like (Official Video), [Lyrics], ft. xyz from title
    import re
    clean_title = re.sub(r'[\(\[].*?[\)\]]', '', title).strip()
    clean_title = re.sub(r'(official|video|lyrics?|audio|ft\.?|feat\.?).*', '', clean_title, flags=re.I).strip()

    queries = []
    if artist and clean_title:
        queries.append(f"{artist} {clean_title} similar songs")
        queries.append(f"songs like {clean_title} {artist}")
        queries.append(f"{artist} best songs")
        queries.append(f"{artist} discography")
    elif artist:
        queries.append(f"{artist} best songs")
        queries.append(f"{artist} popular songs")
        queries.append(f"songs like {artist}")
    elif clean_title:
        queries.append(f"songs like {clean_title}")
        queries.append(clean_title + " similar")

    seen = {track["video_id"]}  # exclude the seed track itself
    unique = []

    for q in queries:
        if len(unique) >= size:
            break
        results = _ytdlp_search(q, 10)
        for t in results:
            if t["video_id"] not in seen and t["duration"] and t["duration"] < 600:
                seen.add(t["video_id"])
                unique.append(t)

    random.shuffle(unique)
    return unique[:size]

def build_auto_queue(seed_track=None, size=40):
    """Build queue. If we have a seed track, base it on that. Otherwise use YTMusic auth."""
    if seed_track:
        return seed_queue_from_track(seed_track, size)

    # try YTMusic auth
    liked   = fetch_liked_songs(50)
    history = fetch_history(30)
    pool    = liked + history
    seen, unique = set(), []
    for t in pool:
        if t["video_id"] not in seen:
            seen.add(t["video_id"]); unique.append(t)

    if unique:
        random.shuffle(unique)
        return unique[:size]

    # totally unauthenticated and no seed — return empty, wait for user
    return []

# ═══════════════════════════════════════════════════════════════════════════
# PLAYBACK
# ═══════════════════════════════════════════════════════════════════════════

def resolve_audio_url(video_id):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "format": "bestaudio/best", "noplaylist": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        for fmt in sorted(info.get("formats",[]), key=lambda f: f.get("abr",0) or 0, reverse=True):
            if fmt.get("vcodec") == "none" and fmt.get("url"):
                return fmt["url"]
        return info.get("url")
    except Exception as e:
        log.error(f"resolve {video_id}: {e}"); return None

def _kill_player():
    """Kill mpv process. Must be called with play_lock held."""
    global player_proc, ipc_socket, is_paused
    if player_proc:
        try:
            player_proc.terminate()
            player_proc.wait(timeout=3)
        except Exception:
            try: player_proc.kill()
            except Exception: pass
        player_proc = None
    # clean up socket file
    if ipc_socket:
        try: Path(ipc_socket).unlink(missing_ok=True)
        except Exception: pass
        ipc_socket = None
    is_paused = False

def play_track(track):
    """Resolve URL and start mpv. Thread-safe via play_lock."""
    global player_proc, ipc_socket, is_paused, play_serial

    with play_lock:
        _kill_player()
        my_serial = play_serial + 1
        play_serial = my_serial
        state["loading"]  = True
        state["current"]  = track
        state["playing"]  = False
        state["progress"] = 0
        state["error"]    = None
        is_paused = False

    log.info(f"▶ resolving: {track['title']}")
    url = resolve_audio_url(track["video_id"])

    with play_lock:
        # if another play_track fired while we were resolving, bail
        if play_serial != my_serial:
            log.info("play_track superseded, bailing")
            return
        state["loading"] = False
        if not url:
            state["error"]   = "Could not load audio"
            state["playing"] = False
            threading.Thread(target=auto_next, daemon=True).start()
            return

        # unique IPC socket path
        sock_path = str(Path(tempfile.gettempdir()) / f"biscuit_{my_serial}.sock")
        ipc_socket = sock_path

        cmd = [
            "mpv",
            "--no-video",
            "--really-quiet",
            f"--volume={state['volume']}",
            f"--input-ipc-server={sock_path}",
            url,
        ]
        player_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        state["playing"] = True

    # watch for natural end
    threading.Thread(target=_watcher, args=(my_serial,), daemon=True).start()
    # track progress via IPC
    threading.Thread(target=_progress_tracker, args=(my_serial, track.get("duration",0)), daemon=True).start()

def _watcher(serial):
    """Wait for mpv to exit, then auto-next (if still our turn)."""
    global player_proc
    proc = None
    with play_lock:
        if play_serial == serial:
            proc = player_proc
    if proc:
        proc.wait()
    with play_lock:
        if play_serial != serial:
            return  # superseded
        if is_paused:
            return  # user paused
    if state["playing"]:
        auto_next()

def _progress_tracker(serial, duration):
    """Poll mpv every second for real position."""
    time.sleep(1)  # give mpv time to start
    while True:
        with play_lock:
            if play_serial != serial or not state["playing"] or is_paused:
                break
        pos = mpv_get_pos()
        with play_lock:
            if play_serial != serial:
                break
            state["progress"] = int(pos) if pos else state["progress"]
        time.sleep(1)

def auto_next():
    """Advance to next track."""
    q   = state["queue"]
    idx = state["queue_index"]

    if state["repeat"] and state["current"]:
        play_track(state["current"]); return

    next_idx = idx + 1

    # refill near end — seed from current track
    if next_idx >= len(q) - 5:
        cur = state["current"]
        if cur:
            more = seed_queue_from_track(cur, size=20)
            existing = {t["video_id"] for t in q}
            for t in more:
                if t["video_id"] not in existing:
                    q.append(t)

    if next_idx < len(q):
        state["queue_index"] = next_idx
        play_track(q[next_idx])
    else:
        with play_lock:
            state["playing"] = False
            state["current"] = None

# ═══════════════════════════════════════════════════════════════════════════
# FLASK API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/state")
def api_state():
    q   = state["queue"]
    idx = state["queue_index"]
    return jsonify({
        "playing":    state["playing"],
        "paused":     is_paused,
        "loading":    state["loading"],
        "current":    state["current"],
        "queue":      q[idx:idx+20],   # send more so remove works
        "volume":     state["volume"],
        "progress":   state["progress"],
        "shuffle":    state["shuffle"],
        "repeat":     state["repeat"],
        "error":      state["error"],
        "ytm_auth":   ytm is not None,
        "queue_len":  len(q),
    })

@app.route("/api/play", methods=["POST"])
def api_play():
    data = request.json or {}
    vid  = data.get("video_id")

    if vid:
        track = {
            "video_id":  vid,
            "title":     data.get("title", "Unknown"),
            "artist":    data.get("artist", ""),
            "thumbnail": data.get("thumbnail", ""),
            "duration":  data.get("duration", 0),
        }
        # check if already in queue
        q = state["queue"]
        for i, t in enumerate(q):
            if t["video_id"] == vid:
                state["queue_index"] = i
                threading.Thread(target=play_track, args=(t,), daemon=True).start()
                # still rebuild queue around it in background
                threading.Thread(target=_rebuild_around, args=(track,), daemon=True).start()
                return jsonify({"ok": True})
        # not in queue — play it and rebuild queue around it
        state["queue"]       = [track]
        state["queue_index"] = 0
        threading.Thread(target=play_track, args=(track,), daemon=True).start()
        threading.Thread(target=_rebuild_around, args=(track,), daemon=True).start()
    else:
        q = state["queue"]
        if not q:
            state["error"] = "Use Search to find a song and start playing."
        else:
            t = q[state["queue_index"]]
            threading.Thread(target=play_track, args=(t,), daemon=True).start()
    return jsonify({"ok": True})

def _rebuild_around(track):
    """Rebuild the queue around a track while it's already playing."""
    log.info(f"Building queue around: {track['title']} — {track['artist']}")
    similar = seed_queue_from_track(track, size=30)
    if not similar:
        log.warning("No similar songs found")
        return
    # put current track at index 0, similar songs after
    state["queue"]       = [track] + similar
    state["queue_index"] = 0
    log.info(f"Queue rebuilt: {len(similar)} songs after {track['title']}")

@app.route("/api/queue/seed", methods=["POST"])
def api_seed_queue():
    """Build a fresh queue seeded from a user-supplied vibe/genre string."""
    vibe = (request.json or {}).get("vibe", "").strip()
    if not vibe:
        return jsonify({"ok": False, "error": "no vibe"})
    def _seed():
        results = _ytdlp_search(vibe, 20)
        if not results:
            state["error"] = f"Nothing found for: {vibe}"
            return
        seen = set()
        unique = []
        for t in results:
            if t["video_id"] not in seen:
                seen.add(t["video_id"]); unique.append(t)
        random.shuffle(unique)
        state["queue"]       = unique
        state["queue_index"] = 0
        state["error"]       = None
        play_track(unique[0])
    threading.Thread(target=_seed, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/pause", methods=["POST"])
def api_pause():
    global is_paused
    with play_lock:
        ok = mpv_set_pause(True)
        if ok:
            is_paused = True
            state["playing"] = False
    return jsonify({"ok": True})

@app.route("/api/resume", methods=["POST"])
def api_resume():
    global is_paused
    with play_lock:
        if player_proc and player_proc.poll() is None:
            ok = mpv_set_pause(False)
            if ok:
                is_paused = False
                state["playing"] = True
                return jsonify({"ok": True})
    # mpv is gone — restart track from beginning
    q   = state["queue"]
    idx = state["queue_index"]
    if idx < len(q):
        threading.Thread(target=play_track, args=(q[idx],), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/next", methods=["POST"])
def api_next():
    threading.Thread(target=auto_next, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/prev", methods=["POST"])
def api_prev():
    idx = state["queue_index"]
    if idx > 0:
        state["queue_index"] = idx - 1
        t = state["queue"][state["queue_index"]]
        threading.Thread(target=play_track, args=(t,), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/volume", methods=["POST"])
def api_volume():
    vol = max(0, min(100, int(request.json.get("volume", 80))))
    state["volume"] = vol
    mpv_set_volume(vol)  # live update via IPC
    return jsonify({"ok": True, "volume": vol})

@app.route("/api/queue/remove", methods=["POST"])
def api_remove():
    """Remove a track from the queue by video_id."""
    vid = (request.json or {}).get("video_id")
    if not vid:
        return jsonify({"ok": False, "error": "no video_id"})
    q   = state["queue"]
    idx = state["queue_index"]
    for i, t in enumerate(q):
        if t["video_id"] == vid:
            q.pop(i)
            # adjust index if we removed something before current
            if i < idx:
                state["queue_index"] = max(0, idx - 1)
            elif i == idx:
                # removed the currently playing track — next will auto-play
                state["queue_index"] = min(idx, len(q) - 1)
            break
    return jsonify({"ok": True, "queue_len": len(q)})

@app.route("/api/search")
def api_search():
    q = request.args.get("q","").strip()
    if not q: return jsonify({"results": []})
    results = search_tracks(q, limit=12)
    return jsonify({"results": results})

@app.route("/api/queue/refresh", methods=["POST"])
def api_refresh_queue():
    seed = state["current"]["video_id"] if state["current"] else None
    threading.Thread(target=_rebuild_queue, args=(seed,), daemon=True).start()
    return jsonify({"ok": True})

def _rebuild_queue(seed=None):
    cur = state["current"]
    if cur:
        _rebuild_around(cur)
    else:
        state["error"] = "Play a song first, then refresh to build a queue around it."

@app.route("/api/toggle/shuffle", methods=["POST"])
def api_shuffle():
    state["shuffle"] = not state["shuffle"]
    if state["shuffle"]:
        idx = state["queue_index"]
        rest = state["queue"][idx+1:]
        random.shuffle(rest)
        state["queue"] = state["queue"][:idx+1] + rest
    return jsonify({"shuffle": state["shuffle"]})

@app.route("/api/toggle/repeat", methods=["POST"])
def api_repeat():
    state["repeat"] = not state["repeat"]
    return jsonify({"repeat": state["repeat"]})

@app.route("/")
def index():
    return send_from_directory("templates", "index.html")

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_ytmusic()
    # do NOT auto-start — wait for user to press play
    log.info("🍪 Biscuit ready at http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
