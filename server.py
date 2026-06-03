#!/usr/bin/env python3

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
    "loading":     False,
}

play_lock    = threading.Lock()
player_proc  = None
ipc_socket   = None
is_paused    = False
play_serial  = 0 

ytm = None
AUTH_FILE = Path("oauth.json")

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

def init_ytmusic():
    global ytm
    if not YTM_AVAILABLE:
        return
    if AUTH_FILE.exists():
        try:
            ytm = YTMusic(str(AUTH_FILE))
            log.info("YTMusic authenticated ✓")
        except Exception as e:
            log.error(f"YTMusic auth failed: {e}")
            ytm = None

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

def build_auto_queue(seed_id=None, size=40):
    liked   = fetch_liked_songs(50)
    history = fetch_history(30)
    recs    = fetch_recommendations(seed_id, 20) if seed_id else []
    pool    = liked + history + recs
    seen, unique = set(), []
    for t in pool:
        if t["video_id"] not in seen:
            seen.add(t["video_id"]); unique.append(t)
    if not unique:
        log.warning("Queue empty — no auth, no seed. Waiting for user search.")
    else:
        random.shuffle(unique)
    return unique[:size]

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
        if play_serial != my_serial:
            log.info("play_track superseded, bailing")
            return
        state["loading"] = False
        if not url:
            state["error"]   = "Could not load audio"
            state["playing"] = False
            threading.Thread(target=auto_next, daemon=True).start()
            return

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

    threading.Thread(target=_watcher, args=(my_serial,), daemon=True).start()
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
            return
        if is_paused:
            return
    if state["playing"]:
        auto_next()

def _progress_tracker(serial, duration):
    """Poll mpv every second for real position."""
    time.sleep(1)
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

    if next_idx >= len(q) - 5:
        seed = state["current"]["video_id"] if state["current"] else None
        more = build_auto_queue(seed_id=seed, size=20)
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

@app.route("/api/state")
def api_state():
    q   = state["queue"]
    idx = state["queue_index"]
    return jsonify({
        "playing":    state["playing"],
        "paused":     is_paused,
        "loading":    state["loading"],
        "current":    state["current"],
        "queue":      q[idx:idx+20],
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
        q = state["queue"]
        for i, t in enumerate(q):
            if t["video_id"] == vid:
                state["queue_index"] = i
                threading.Thread(target=play_track, args=(t,), daemon=True).start()
                return jsonify({"ok": True})
        track = {
            "video_id":  vid,
            "title":     data.get("title","Unknown"),
            "artist":    data.get("artist",""),
            "thumbnail": data.get("thumbnail",""),
            "duration":  data.get("duration", 0),
        }
        idx = state["queue_index"]
        q.insert(idx + 1, track)
        state["queue_index"] = idx + 1
        threading.Thread(target=play_track, args=(track,), daemon=True).start()
    else:
        q = state["queue"]
        if not q:
            state["loading"] = True
            threading.Thread(target=_init_and_play, daemon=True).start()
        else:
            t = q[state["queue_index"]]
            threading.Thread(target=play_track, args=(t,), daemon=True).start()
    return jsonify({"ok": True})

def _init_and_play():
    q = build_auto_queue(size=40)
    state["queue"]       = q
    state["queue_index"] = 0
    state["loading"]     = False
    if q:
        play_track(q[0])
    else:
        state["error"] = "No songs found. Sign in or use Search to play something."

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
    mpv_set_volume(vol)
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
            if i < idx:
                state["queue_index"] = max(0, idx - 1)
            elif i == idx:
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
    q = build_auto_queue(seed_id=seed, size=40)
    cur_id = state["current"]["video_id"] if state["current"] else None
    state["queue"] = q
    if cur_id:
        for i, t in enumerate(q):
            if t["video_id"] == cur_id:
                state["queue_index"] = i
                return
    state["queue_index"] = 0

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

if __name__ == "__main__":
    init_ytmusic()
    log.info("Biscuit ready at http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
