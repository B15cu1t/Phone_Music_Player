#!/usr/bin/env python3

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

    ver = tuple(int(x) for x in ytmusicapi.__version__.split(".")[:2])
    print(f"\n  ytmusicapi version: {ytmusicapi.__version__}")

    if auth_file.exists() or browser_file.exists():
        existing = auth_file if auth_file.exists() else browser_file
        print(f"\n  ✓ Already authenticated ({existing})")
        resp = input("  Re-authenticate? [y/N]: ").strip().lower()
        if resp != "y":
            return

    print("\n── YouTube Music Login ──────────────────────────────────────")
    print("  Links Biscuit to your account for liked songs,")
    print("  history and personal recommendations.")
    print()

    print("  METHOD: Browser headers (works with all versions)")
    print()
    print("  Steps:")
    print("  1. Open music.youtube.com in your browser")
    print("  2. Press F12 to open DevTools")
    print("  3. Go to Network tab")
    print("  4. Play any song (so a request fires)")
    print("  5. Click any request to music.youtube.com")
    print("  6. Scroll to 'Request Headers'")
    print("  7. Right-click → Copy → Copy as cURL")
    print()
    print("  Then paste it below and press Enter twice when done.")
    print("─────────────────────────────────────────────────────────────")
    print()

    has_oauth = hasattr(YTMusic, 'setup_oauth')

    if has_oauth:
        print("  OAuth is available — using that instead (easier).")
        print("  A link will appear — open it in your browser and log in.")
        input("  Press Enter to start...")
        try:
            YTMusic.setup_oauth(filepath=str(auth_file))
            print(f"\n  ✓ Saved to {auth_file}")
            return
        except Exception as e:
            print(f"  OAuth failed ({e}), falling back to browser method...")

    print("  Paste the cURL command (or just the Cookie header value).")
    print("  Press Enter twice when done:\n")
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
        print("\n  Nothing entered — skipping auth.")
        print("  You can re-run setup.py later, or use Search to play music.")
        return

    try:
        YTMusic.setup(filepath=str(browser_file), headers_raw=raw)
        print(f"\n  ✓ Saved to {browser_file}")
    except Exception as e:
        print(f"\n  ✗ Failed to parse headers: {e}")
        print("  Try copying just the Cookie: header value instead.")

def main():
    os.chdir(Path(__file__).parent)
    print()
    print("  ● biscuit — setup")
    print("  ─────────────────────────────")

    missing = check_deps()
    if missing:
        install_deps(missing)
    print("  ✓ python deps ready")

    if check_mpv():
        print("  ✓ mpv ready")
    else:
        print()
        print("  ✗ mpv not found. Install it:")
        print("    Termux:  pkg install mpv")
        sys.exit(1)

    setup_auth()

    print()
    print("  ─────────────────────────────")
    print("  done. start with: python server.py")
    print("  then open http://127.0.0.1:5000")
    print()

if __name__ == "__main__":
"""
setup.py — Run this ONCE before starting the server.
Handles:
  1. Dependency check
  2. YTMusic OAuth login (saves oauth.json)
"""

import subprocess
import sys
import os
from pathlib import Path

REQUIRED = ["flask", "yt-dlp", "ytmusicapi"]

def check_deps():
    missing = []
    for pkg in REQUIRED:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)
    return missing

def install_deps(pkgs):
    print(f"Installing: {', '.join(pkgs)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *pkgs])

def check_mpv():
    try:
        subprocess.run(["mpv", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def setup_ytmusic_auth():
    from ytmusicapi import YTMusic
    auth_file = Path("oauth.json")

    if auth_file.exists():
        print(f"\n✓ Already authenticated ({auth_file})")
        resp = input("  Re-authenticate? [y/N]: ").strip().lower()
        if resp != "y":
            return

    print("\n── YTMusic Authentication ─────────────────────────────────────")
    print("This links the player to your YouTube account for:")
    print("  • Liked songs")
    print("  • Watch history")
    print("  • Personalized recommendations")
    print()
    print("Starting OAuth flow — a browser link will appear.")
    print("Log in with your Google account when prompted.")
    print("─────────────────────────────────────────────────────────────────")
    input("Press Enter to continue…")

    try:
        YTMusic.setup_oauth(filepath=str(auth_file))
        print(f"\n✓ Authentication saved to {auth_file}")
    except Exception as e:
        print(f"\n✗ Auth failed: {e}")
        print("  You can still use the player without auth (unauthenticated search mode).")

def main():
    print("═══════════════════════════════════════════════")
    print("   YTMusic Phone Player — Setup")
    print("═══════════════════════════════════════════════\n")

    # 1. Python deps
    missing = check_deps()
    if missing:
        install_deps(missing)
        print("✓ Dependencies installed\n")
    else:
        print("✓ All Python dependencies present\n")

    # 2. mpv
    if check_mpv():
        print("✓ mpv found\n")
    else:
        print("✗ mpv not found!")
        print("  Install it with:")
        print("    Termux:  pkg install mpv")
        print("    Ubuntu:  sudo apt install mpv")
        print("    macOS:   brew install mpv\n")
        sys.exit(1)

    # 3. YTMusic auth
    setup_ytmusic_auth()

    print("\n═══════════════════════════════════════════════")
    print("  Setup complete! Start the player with:")
    print("  python server.py")
    print()
    print("  Then open http://localhost:5000 in your browser.")
    print("  On Android/Termux, open http://127.0.0.1:5000")
    print("═══════════════════════════════════════════════\n")

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    main()
