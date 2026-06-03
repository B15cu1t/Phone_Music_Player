#!/usr/bin/env python3
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
