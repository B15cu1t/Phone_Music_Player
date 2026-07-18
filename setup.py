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

def check_termux_api():
    try:
        subprocess.run(["termux-media-session","--help"], capture_output=True, timeout=3)
        return True
    except: return False

def is_termux():
    return Path("/data/data/com.termux").exists()

def main():
    os.chdir(Path(__file__).parent)
    print()
    print("  biscuit — setup")
    print("  ───────────────")

    # python deps
    missing = []
    for pkg in REQUIRED:
        try: __import__(pkg.replace("-","_"))
        except ImportError: missing.append(pkg)
    if missing:
        print(f"  installing {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    print("  deps ok")

    # mpv
    if not check_mpv():
        print("  mpv missing — run: pkg install mpv")
        sys.exit(1)
    print("  mpv ok")

    # termux-api (lockscreen controls)
    if is_termux():
        if check_termux_api():
            print("  termux-api ok (lockscreen controls active)")
        else:
            print("  termux-api missing — installing...")
            try:
                subprocess.check_call(["pkg", "install", "termux-api", "curl", "-y"])
                print("  termux-api ok")
                print("  ! also install the Termux:API app from F-Droid for lockscreen support")
                print("    https://f-droid.org/packages/com.termux.api/")
            except Exception as e:
                print(f"  termux-api install failed: {e}")
                print("  run manually: pkg install termux-api")

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
