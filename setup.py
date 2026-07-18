#!/usr/bin/env python3
"""
Biscuit Music Player — setup.py
Run once before starting the server.
"""
import subprocess, sys, os
from pathlib import Path

REQUIRED = ["flask", "yt-dlp", "ytmusicapi"]

def is_termux():
    return "com.termux" in os.environ.get("PREFIX", "") or \
           Path("/data/data/com.termux").exists()

def check_mpv():
    try:
        subprocess.run(["mpv", "--version"], capture_output=True, check=True)
        return True
    except:
        return False

def check_termux_api():
    """Check if termux-media-session is available (from termux-api pkg)."""
    try:
        subprocess.run(["termux-media-session", "--help"],
                       capture_output=True, timeout=3)
        return True
    except:
        return False

def main():
    os.chdir(Path(__file__).parent)
    print()
    print("  biscuit — setup")
    print("  ───────────────")

    # 1. Python deps
    missing = []
    for pkg in REQUIRED:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"  installing {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    print("  ✓ python deps")

    # 2. mpv
    if not check_mpv():
        print()
        print("  ✗ mpv not found.")
        if is_termux():
            print("    run: pkg install mpv")
        else:
            print("    ubuntu: sudo apt install mpv")
            print("    mac:    brew install mpv")
        sys.exit(1)
    print("  ✓ mpv")

    # 3. Termux:API — needed for lockscreen / media notification
    if is_termux():
        if check_termux_api():
            print("  ✓ termux-api (lockscreen controls active)")
        else:
            print()
            print("  ! termux-api not found — lockscreen controls won't work.")
            print("    to fix, run:")
            print("      pkg install termux-api")
            print("    AND install the Termux:API app from F-Droid:")
            print("      https://f-droid.org/packages/com.termux.api/")
            print()
            resp = input("  install termux-api now? [Y/n]: ").strip().lower()
            if resp != "n":
                try:
                    subprocess.check_call(["pkg", "install", "termux-api", "-y"])
                    print("  ✓ termux-api installed")
                    print("  ! still need the Termux:API app from F-Droid for full lockscreen support")
                except Exception as e:
                    print(f"  failed: {e} — install manually with: pkg install termux-api")

    print()
    print("  ───────────────")
    print("  all good. start with:")
    print("    python server.py")
    print()
    print("  then open http://127.0.0.1:5000")
    print("  tip: add to home screen in Chrome for app-like experience")
    print()

if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
Biscuit setup — installs deps and checks mpv.
Auth is optional and can be done later.
"""
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
    main()
