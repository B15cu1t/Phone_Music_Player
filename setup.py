#!/usr/bin/env python3
import subprocess, sys, os
from pathlib import Path

REQUIRED = ["flask", "yt-dlp", "ytmusicapi"]

def check_mpv():
    try:
        subprocess.run(["mpv","--version"], capture_output=True, check=True)
        return True
    except: return False

def main():
    os.chdir(Path(__file__).parent)
    print()
    print("  biscuit — setup")
    print("  ───────────────")

    # install deps
    missing = []
    for pkg in REQUIRED:
        try: __import__(pkg.replace("-","_"))
        except ImportError: missing.append(pkg)
    if missing:
        print(f"  installing {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    print("  deps ok")

    if not check_mpv():
        print("  mpv missing — run: pkg install mpv")
        sys.exit(1)
    print("  mpv ok")

    print()
    print("  ───────────────")
    print("  all good. start with:")
    print("  python server.py")
    print()
    print("  then open http://127.0.0.1:5000")
    print("  use the Search tab to find music and build your queue")
    print()

if __name__ == "__main__":
    main()#!/usr/bin/env python3
import subprocess, sys, os
from pathlib import Path

REQUIRED = ["flask", "yt-dlp", "ytmusicapi"]

def check_deps():
    missing = []
    for pkg in REQUIRED:
        try: __import__(pkg.replace("-","_"))
        except ImportError: missing.append(pkg)
    return missing

def install_deps(pkgs):
    print(f"  installing: {', '.join(pkgs)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *pkgs])

def check_mpv():
    try:
        subprocess.run(["mpv","--version"], capture_output=True, check=True)
        return True
    except: return False

def setup_auth():
    from ytmusicapi import YTMusic
    import ytmusicapi
    auth_file = Path("oauth.json")
    browser_file = Path("browser.json")

    print(f"\n  ytmusicapi version: {ytmusicapi.__version__}")

    if auth_file.exists() or browser_file.exists():
        existing = auth_file if auth_file.exists() else browser_file
        print(f"\n  Already authenticated ({existing})")
        resp = input("  Re-authenticate? [y/N]: ").strip().lower()
        if resp != "y":
            return

    print("\n── YouTube Music Login ──────────────────────────────────────")
    print("  Steps:")
    print("  1. Open music.youtube.com in your browser")
    print("  2. Press F12 -> Network tab")
    print("  3. Play any song so a request fires")
    print("  4. Click any request to music.youtube.com")
    print("  5. Right-click the request -> Copy -> Copy as cURL")
    print("  6. Paste it below, then press Enter twice")
    print("─────────────────────────────────────────────────────────────\n")

    lines = []
    try:
        while True:
            line = input()
            if line == "" and lines and lines[-1] == "":
                break
            lines.append(line)
    except EOFError:
        pass

    raw = "\n".join(lines).strip()
    if not raw:
        print("\n  Skipping auth — use Search to play music without it.")
        return

    try:
        YTMusic.setup(filepath=str(browser_file), headers_raw=raw)
        print(f"\n  Saved to {browser_file}")
    except Exception as e:
        print(f"\n  Failed: {e}")
        print("  Try again or skip and use Search.")

def main():
    os.chdir(Path(__file__).parent)
    print("\n  biscuit — setup")
    print("  ─────────────────────────────")

    missing = check_deps()
    if missing:
        install_deps(missing)
    print("  deps ready")

    if check_mpv():
        print("  mpv ready")
    else:
        print("  mpv not found — run: pkg install mpv")
        sys.exit(1)

    setup_auth()

    print("\n  ─────────────────────────────")
    print("  done. run: python server.py")
    print("  then open http://127.0.0.1:5000\n")

if __name__ == "__main__":
    main()
