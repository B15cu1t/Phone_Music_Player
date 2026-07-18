#!/usr/bin/env python3
"""
Biscuit Music Player - server.py
Overhauled: taste memory, smart diverse queuing, blacklist, cover/reaction filtering.
"""

import os, json, re, random, threading, subprocess, time, logging, socket, tempfile
from pathlib import Path
from collections import defaultdict
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

TASTE_FILE = Path("taste.json")

def _load_taste():
    if TASTE_FILE.exists():
        try:
            return json.loads(TASTE_FILE.read_text())
        except Exception:
            pass
    return {
        "artists":    {},   # artist -> play_count
        "genres":     {},   # genre/tag -> play_count
        "blacklist":  [],   # video_ids never to play again
        "skip_count": {},   # video_id -> times skipped quickly
        "played":     [],   # last 200 video_ids (avoid recent repeats)
    }

def _save_taste():
    try:
        TASTE_FILE.write_text(json.dumps(taste, indent=2))
    except Exception as e:
        log.error(f"save taste: {e}")

taste = _load_taste()
taste_lock = threading.Lock()

def record_play(track):
    """Call when a track plays for >30s — counts as a real listen."""
    with taste_lock:
        artist = _clean_artist(track.get("artist",""))
        if artist:
            taste["artists"][artist] = taste["artists"].get(artist, 0) + 1

        vid = track.get("video_id","")
        if vid:
            played = taste["played"]
            if vid in played:
                played.remove(vid)
            played.append(vid)
            taste["played"] = played[-200:]  # keep last 200

        _save_taste()

def record_skip(track):
    """Call when user skips quickly (<10s) — signals dislike."""
    with taste_lock:
        vid = track.get("video_id","")
        if vid:
            taste["skip_count"][vid] = taste["skip_count"].get(vid, 0) + 1
            # auto-blacklist after 3 quick skips
            if taste["skip_count"][vid] >= 3:
                if vid not in taste["blacklist"]:
                    taste["blacklist"].append(vid)
                    log.info(f"Auto-blacklisted: {track.get('title')}")
        _save_taste()

def blacklist_track(video_id):
    with taste_lock:
        if video_id not in taste["blacklist"]:
            taste["blacklist"].append(video_id)
        _save_taste()

def is_blacklisted(video_id):
    return video_id in taste["blacklist"]

def recently_played(video_id):
    """True if played in last 50 tracks."""
    return video_id in taste["played"][-50:]

def top_artists(n=10):
    """Return top N most-played artists."""
    with taste_lock:
        ranked = sorted(taste["artists"].items(), key=lambda x: x[1], reverse=True)
        return [a for a, _ in ranked[:n]]

def _clean_artist(artist):
    """Strip 'VEVO', 'Topic', featured artists etc."""
    a = re.sub(r'\s*-\s*(VEVO|Topic|Official).*', '', artist, flags=re.I)
    a = re.sub(r'\s*(ft\.?|feat\.?|&|,).*', '', a, flags=re.I)
    return a.strip()

JUNK_TITLE_PATTERNS = re.compile(
    r'\b(cover|reaction|reacts?|reacting|review|responds?|responds to|'
    r'ranking|ranked|tier list|compilation|best of|top \d+|hours? of|'
    r'extended|slowed|reverb|nightcore|sped up|speed up|karaoke|'
    r'instrumental|piano version|acoustic version|violin|guitar cover|'
    r'drum cover|bass cover|lesson|tutorial|how to play|tab|'
    r'lyric video|lyrics|official lyrics|sub español|traducida|'
    r'full album|full ep|discography)\b',
    re.IGNORECASE
)

JUNK_UPLOADER_PATTERNS = re.compile(
    r'\b(covers|reactions|reacts|reviews|karaoke|lyrics?|fan|fans)\b',
    re.IGNORECASE
)

def is_junk(track):
    """Return True if this looks like a cover, reaction, compilation, etc."""
    title    = track.get("title", "")
    uploader = track.get("artist", "")
    dur      = track.get("duration", 0) or 0

    if JUNK_TITLE_PATTERNS.search(title):
        return True
    if JUNK_UPLOADER_PATTERNS.search(uploader):
        return True
    if dur > 900 or (dur > 0 and dur < 60):
        return True
    return False

def is_same_song(track, seed_title, seed_artist):
    """Detect if a search result is just the same song we searched for."""
    t = track.get("title","").lower()
    a = track.get("artist","").lower()
    st = seed_title.lower()
    sa = seed_artist.lower()
    # same title by same artist = same song
    if _title_similarity(t, st) > 0.7 and sa and sa[:6] in a:
        return True
    return False

def _title_similarity(a, b):
    """Rough word overlap ratio."""
    wa = set(re.findall(r'\w+', a))
    wb = set(re.findall(r'\w+', b))
    if not wa or not wb:
        return 0
    return len(wa & wb) / max(len(wa), len(wb))

def filter_tracks(tracks, seed_title="", seed_artist=""):
    """Remove junk, blacklisted, recently played, and same-song duplicates."""
    out = []
    for t in tracks:
        vid = t.get("video_id","")
        if not vid:                              continue
        if is_blacklisted(vid):                  continue
        if recently_played(vid):                 continue
        if is_junk(t):                           continue
        if is_same_song(t, seed_title, seed_artist): continue
        out.append(t)
    return out
    
GENRE_GRAPH = {
    # metal/hard rock
    "slipknot":      ["korn", "system of a down", "deftones", "disturbed", "five finger death punch", "lamb of god"],
    "korn":          ["slipknot", "limp bizkit", "deftones", "mudvayne", "static-x"],
    "metallica":     ["megadeth", "slayer", "pantera", "anthrax", "testament", "death"],
    "system of a down": ["rage against the machine", "deftones", "tool", "slipknot"],
    "tool":          ["system of a down", "deftones", "alice in chains", "perfect circle", "porcupine tree"],
    "deftones":      ["tool", "korn", "slipknot", "incubus", "glassjaw"],
    "disturbed":     ["breaking benjamin", "five finger death punch", "shinedown", "godsmack"],
    # emo/alt
    "my chemical romance": ["panic at the disco", "fall out boy", "the used", "a day to remember", "paramore"],
    "fall out boy":  ["my chemical romance", "panic at the disco", "paramore", "all time low"],
    "paramore":      ["hayley williams", "fall out boy", "my chemical romance", "new found glory"],
    "the used":      ["my chemical romance", "hawthorne heights", "thursday", "underoath"],
    # rap/hip-hop
    "eminem":        ["d12", "50 cent", "dr dre", "kendrick lamar", "logic"],
    "kendrick lamar":["j. cole", "drake", "tyler the creator", "schoolboy q", "ab-soul"],
    "21 savage":     ["metro boomin", "young thug", "gunna", "lil baby", "future"],
    "travis scott":  ["drake", "don toliver", "quavo", "future", "young thug"],
    # indie/alt
    "arctic monkeys":["the strokes", "the killers", "interpol", "foals", "the 1975"],
    "the strokes":   ["arctic monkeys", "interpol", "yeah yeah yeahs", "tv on the radio"],
    "billie eilish": ["olivia rodrigo", "lorde", "lana del rey", "phoebe bridgers"],
    # rock
    "foo fighters":  ["nirvana", "radiohead", "pearl jam", "alice in chains", "soundgarden"],
    "nirvana":       ["foo fighters", "pearl jam", "soundgarden", "alice in chains", "mudhoney"],
}

def get_related_artists(artist):
    """Get related artists from genre graph, plus the artist's own name."""
    clean = _clean_artist(artist).lower()
    related = []
    for key, vals in GENRE_GRAPH.items():
        if key in clean or clean in key:
            related.extend(vals)
            break
        for v in vals:
            if v in clean or clean in v:
                related.append(key)
                related.extend(vals)
                break
    # deduplicate, exclude self
    seen = set()
    out = []
    for a in related:
        if a not in seen and a not in clean:
            seen.add(a)
            out.append(a)
    return out[:6]

def _ytdlp_search(query, limit=10):
    try:
        opts = {
            "quiet": True,
            "extract_flat": True,
            "default_search": "ytsearch",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        results = []
        for e in info.get("entries", []):
            if not e: continue
            results.append({
                "video_id":  e.get("id",""),
                "title":     e.get("title","Unknown"),
                "artist":    e.get("uploader","Unknown Artist"),
                "thumbnail": e.get("thumbnail",""),
                "duration":  e.get("duration", 0),
            })
        return results
    except Exception as e:
        log.error(f"ytdlp search '{query}': {e}")
        return []

def smart_search(artist, title="", limit=8):
    """
    Search for songs by an artist in a way that avoids covers and reactions.
    Uses multiple query strategies and deduplicates.
    """
    clean_artist = _clean_artist(artist)
    clean_title  = re.sub(r'[\(\[].*?[\)\]]', '', title).strip()
    clean_title  = re.sub(r'(official|video|lyrics?|audio|ft\.?|feat\.?).*', '', clean_title, flags=re.I).strip()

    queries = [
        f'{clean_artist} official audio',
        f'{clean_artist} songs',
        f'{clean_artist} full song',
    ]
    if clean_title:
        queries.insert(0, f'{clean_artist} {clean_title} official')

    seen = set()
    results = []
    for q in queries:
        if len(results) >= limit:
            break
        batch = _ytdlp_search(q, limit)
        for t in batch:
            if t["video_id"] not in seen:
                seen.add(t["video_id"])
                results.append(t)

    return results

def search_tracks(query, limit=10):
    """Public search — used by the Find tab."""
    if ytm is not None:
        try:
            results = ytm.search(query, filter="songs", limit=limit)
            tracks = [_t(r) for r in results if r.get("videoId")]
            if tracks:
                return tracks
        except Exception as e:
            log.error(f"ytm search: {e}")
    # fallback: yt-dlp but add "official" to reduce junk
    raw = _ytdlp_search(f"{query} official audio", limit + 4)
    filtered = filter_tracks(raw)
    return filtered[:limit]

def seed_queue_from_track(track, size=35):
    """
    Build a diverse queue starting from a seed track.
    Strategy:
      1. More songs by the same artist (but NOT the same song, no covers)
      2. Songs by genre-related artists
      3. Top artists from taste memory (what you've been listening to)
    All filtered for junk and deduplication.
    """
    artist     = track.get("artist", "")
    title      = track.get("title", "")
    video_id   = track.get("video_id", "")

    seen    = {video_id}
    pool    = []

    same_artist_results = smart_search(artist, "", limit=12)
    for t in filter_tracks(same_artist_results, title, artist):
        if t["video_id"] not in seen:
            seen.add(t["video_id"])
            pool.append(t)

    related = get_related_artists(artist)
    random.shuffle(related)
    for rel_artist in related[:4]:
        if len(pool) >= size:
            break
        results = smart_search(rel_artist, limit=6)
        for t in filter_tracks(results):
            if t["video_id"] not in seen:
                seen.add(t["video_id"])
                pool.append(t)

    top = [a for a in top_artists(8) if a.lower() not in artist.lower()]
    random.shuffle(top)
    for ta in top[:3]:
        if len(pool) >= size:
            break
        results = smart_search(ta, limit=5)
        for t in filter_tracks(results):
            if t["video_id"] not in seen:
                seen.add(t["video_id"])
                pool.append(t)
    if len(pool) < 10:
        genre_query = f"{artist} genre similar bands official audio"
        results = _ytdlp_search(genre_query, 10)
        for t in filter_tracks(results, title, artist):
            if t["video_id"] not in seen:
                seen.add(t["video_id"])
                pool.append(t)

    # shuffle but keep it feeling varied (interleave sources)
    random.shuffle(pool)
    return pool[:size]

ytm = None

def init_ytmusic():
    global ytm
    if not YTM_AVAILABLE:
        return
    for candidate in ["browser.json", "oauth.json"]:
        p = Path(candidate)
        if p.exists():
            try:
                ytm = YTMusic(str(p))
                log.info(f"YTMusic authenticated via {candidate} ✓")
                return
            except Exception as e:
                log.error(f"Auth failed ({candidate}): {e}")
    log.warning("No auth file — unauthenticated mode")

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

def mpv_cmd(cmd):
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
        log.debug(f"mpv_cmd: {e}")
        return False

def mpv_set_pause(paused):
    return mpv_cmd({"command": ["set_property", "pause", paused]})

def mpv_set_volume(vol):
    return mpv_cmd({"command": ["set_property", "volume", vol]})

def mpv_get_pos():
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
            if not chunk: break
            data += chunk
            if b"\n" in data: break
        s.close()
        resp = json.loads(data.decode().strip().split("\n")[0])
        return float(resp.get("data", 0) or 0)
    except Exception:
        return 0.0

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

play_lock   = threading.Lock()
player_proc = None
ipc_socket  = None
is_paused   = False
play_serial = 0
play_start_time = 0  # for skip detection

def resolve_audio_url(video_id):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "format": "bestaudio/best", "noplaylist": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        for fmt in sorted(info.get("formats",[]), key=lambda f: f.get("abr",0) or 0, reverse=True):
            if fmt.get("vcodec") == "none" and fmt.get("url"):
                return fmt["url"]
        return info.get("url")
    except Exception as e:
        log.error(f"resolve {video_id}: {e}")
        return None

def _kill_player():
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
    global player_proc, ipc_socket, is_paused, play_serial, play_start_time

    with play_lock:
        # detect quick skip on previous track
        if state["current"] and play_start_time:
            elapsed = time.time() - play_start_time
            if elapsed < 10:
                threading.Thread(target=record_skip, args=(state["current"],), daemon=True).start()

        _kill_player()
        my_serial = play_serial + 1
        play_serial = my_serial
        state["loading"]  = True
        state["current"]  = track
        state["playing"]  = False
        state["progress"] = 0
        state["error"]    = None
        is_paused = False
        play_start_time = 0

    log.info(f"▶ resolving: {track['title']} — {track['artist']}")
    url = resolve_audio_url(track["video_id"])

    with play_lock:
        if play_serial != my_serial:
            log.info("superseded")
            return
        state["loading"] = False
        if not url:
            state["error"]   = "Could not load audio"
            state["playing"] = False
            threading.Thread(target=auto_next, daemon=True).start()
            return

        sock_path  = str(Path(tempfile.gettempdir()) / f"biscuit_{my_serial}.sock")
        ipc_socket = sock_path
        cmd = [
            "mpv", "--no-video", "--really-quiet",
            f"--volume={state['volume']}",
            f"--input-ipc-server={sock_path}",
            url,
        ]
        player_proc     = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        state["playing"] = True
        play_start_time  = time.time()

    threading.Thread(target=_watcher, args=(my_serial,), daemon=True).start()
    threading.Thread(target=_progress_tracker, args=(my_serial,), daemon=True).start()
    # record play after 30s in background
    threading.Thread(target=_delayed_record, args=(my_serial, track), daemon=True).start()

def _delayed_record(serial, track):
    """Record a real listen after 30 seconds."""
    time.sleep(30)
    with play_lock:
        if play_serial != serial: return
    record_play(track)

def _watcher(serial):
    global player_proc
    proc = None
    with play_lock:
        if play_serial == serial:
            proc = player_proc
    if proc:
        proc.wait()
    with play_lock:
        if play_serial != serial: return
        if is_paused: return
    if state["playing"]:
        auto_next()

def _progress_tracker(serial):
    time.sleep(1)
    while True:
        with play_lock:
            if play_serial != serial or not state["playing"] or is_paused:
                break
        pos = mpv_get_pos()
        with play_lock:
            if play_serial != serial: break
            state["progress"] = int(pos) if pos else state["progress"]
        time.sleep(1)

def auto_next():
    q   = state["queue"]
    idx = state["queue_index"]

    if state["repeat"] and state["current"]:
        play_track(state["current"])
        return

    next_idx = idx + 1

    # near end — refill with more smart songs
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

@app.route("/api/state")
def api_state():
    q   = state["queue"]
    idx = state["queue_index"]
    return jsonify({
        "playing":    state["playing"],
        "paused":     is_paused,
        "loading":    state["loading"],
        "current":    state["current"],
        "queue":      q[idx+1:idx+21],  # next 20, not including current
        "volume":     state["volume"],
        "progress":   state["progress"],
        "shuffle":    state["shuffle"],
        "repeat":     state["repeat"],
        "error":      state["error"],
        "ytm_auth":   ytm is not None,
        "queue_len":  len(q),
        "top_artists": top_artists(5),
    })

@app.route("/api/play", methods=["POST"])
def api_play():
    data = request.json or {}
    vid  = data.get("video_id")

    if vid:
        track = {
            "video_id":  vid,
            "title":     data.get("title","Unknown"),
            "artist":    data.get("artist",""),
            "thumbnail": data.get("thumbnail",""),
            "duration":  data.get("duration", 0),
        }
        # check if already in queue
        q = state["queue"]
        for i, t in enumerate(q):
            if t["video_id"] == vid:
                state["queue_index"] = i
                threading.Thread(target=play_track, args=(t,), daemon=True).start()
                threading.Thread(target=_rebuild_around, args=(track,), daemon=True).start()
                return jsonify({"ok": True})
        # new track — play immediately, build queue around it
        state["queue"]       = [track]
        state["queue_index"] = 0
        threading.Thread(target=play_track, args=(track,), daemon=True).start()
        threading.Thread(target=_rebuild_around, args=(track,), daemon=True).start()
    else:
        q = state["queue"]
        if not q:
            state["error"] = "Search for a song to get started."
        else:
            t = q[state["queue_index"]]
            threading.Thread(target=play_track, args=(t,), daemon=True).start()
    return jsonify({"ok": True})

def _rebuild_around(track):
    log.info(f"Building queue around: {track['title']} — {track['artist']}")
    similar = seed_queue_from_track(track, size=35)
    if not similar:
        log.warning("No similar songs found")
        return
    state["queue"]       = [track] + similar
    state["queue_index"] = 0
    log.info(f"Queue ready: {len(similar)} tracks after {track['title']}")

@app.route("/api/pause", methods=["POST"])
def api_pause():
    global is_paused
    with play_lock:
        ok = mpv_set_pause(True)
        if ok:
            is_paused        = True
            state["playing"] = False
    return jsonify({"ok": True})

@app.route("/api/resume", methods=["POST"])
def api_resume():
    global is_paused
    with play_lock:
        if player_proc and player_proc.poll() is None:
            ok = mpv_set_pause(False)
            if ok:
                is_paused        = False
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

@app.route("/api/dislike", methods=["POST"])
def api_dislike():
    """Blacklist a track — never play it again."""
    vid = (request.json or {}).get("video_id")
    if vid:
        blacklist_track(vid)
        # if it's current, skip it
        if state["current"] and state["current"]["video_id"] == vid:
            threading.Thread(target=auto_next, daemon=True).start()
        # remove from queue
        state["queue"] = [t for t in state["queue"] if t["video_id"] != vid]
    return jsonify({"ok": True})

@app.route("/api/volume", methods=["POST"])
def api_volume():
    vol = max(0, min(100, int((request.json or {}).get("volume", 80))))
    state["volume"] = vol
    mpv_set_volume(vol)
    return jsonify({"ok": True, "volume": vol})

@app.route("/api/search")
def api_search():
    q = request.args.get("q","").strip()
    if not q:
        return jsonify({"results": []})
    results = search_tracks(q, limit=12)
    return jsonify({"results": results})

@app.route("/api/queue/refresh", methods=["POST"])
def api_refresh_queue():
    cur = state["current"]
    if cur:
        threading.Thread(target=_rebuild_around, args=(cur,), daemon=True).start()
    else:
        state["error"] = "Play a song first, then refresh."
    return jsonify({"ok": True})

@app.route("/api/queue/remove", methods=["POST"])
def api_remove():
    vid = (request.json or {}).get("video_id")
    if not vid:
        return jsonify({"ok": False})
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
    return jsonify({"ok": True})

@app.route("/api/queue/reorder", methods=["POST"])
def api_reorder():
    """
    Move a track from one position to another.
    Expects: { from_id: video_id, to_id: video_id }
    Inserts the dragged track before the target track.
    """
    data    = request.json or {}
    from_id = data.get("from_id")
    to_id   = data.get("to_id")
    if not from_id or not to_id or from_id == to_id:
        return jsonify({"ok": False})

    q   = state["queue"]
    idx = state["queue_index"]

    # find positions
    from_pos = next((i for i, t in enumerate(q) if t["video_id"] == from_id), None)
    to_pos   = next((i for i, t in enumerate(q) if t["video_id"] == to_id), None)
    if from_pos is None or to_pos is None:
        return jsonify({"ok": False, "error": "track not found"})

    # pull out the moving track
    track = q.pop(from_pos)
    # recalculate to_pos after removal
    if from_pos < to_pos:
        to_pos -= 1
    q.insert(to_pos, track)

    # fix queue_index to keep pointing at the same track
    cur_id = state["current"]["video_id"] if state["current"] else None
    if cur_id:
        for i, t in enumerate(q):
            if t["video_id"] == cur_id:
                state["queue_index"] = i
                break

    return jsonify({"ok": True})

@app.route("/api/queue/seed", methods=["POST"])
def api_seed_queue():
    """Seed the queue from a vibe/genre string."""
    vibe = (request.json or {}).get("vibe","").strip()
    if not vibe:
        return jsonify({"ok": False})
    def _seed():
        results = _ytdlp_search(f"{vibe} official audio", 20)
        filtered = filter_tracks(results)
        if not filtered:
            state["error"] = f"Nothing found for: {vibe}"
            return
        random.shuffle(filtered)
        state["queue"]       = filtered
        state["queue_index"] = 0
        state["error"]       = None
        play_track(filtered[0])
        # rebuild properly around first result
        threading.Thread(target=_rebuild_around, args=(filtered[0],), daemon=True).start()
    threading.Thread(target=_seed, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/taste")
def api_taste():
    return jsonify({
        "top_artists": top_artists(10),
        "blacklist_count": len(taste["blacklist"]),
        "total_plays": sum(taste["artists"].values()),
    })

@app.route("/api/toggle/shuffle", methods=["POST"])
def api_shuffle():
    state["shuffle"] = not state["shuffle"]
    if state["shuffle"]:
        idx  = state["queue_index"]
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
    log.info("🍪 Biscuit ready → http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
