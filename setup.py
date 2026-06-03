#!/usr/bin/env python3
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
