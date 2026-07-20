#!/usr/bin/env python3
"""
Biscuit Music Player — setup.py
Supports: Termux (Android), iSH (iPhone), Linux/Mac
Run once before starting the server.
"""
import subprocess, sys, os, shutil
from pathlib import Path

REQUIRED = ["flask", "yt-dlp", "ytmusicapi"]

# ── detect environment ────────────────────────────────────────────────────

def is_termux():
    return Path("/data/data/com.termux").exists()

def is_ish():
    # iSH runs Alpine Linux on iPhone
    return Path("/etc/alpine-release").exists() or "ish" in os.uname().release.lower()

def pkg_install(packages):
    """Install system packages using the right package manager."""
    if is_termux():
        subprocess.check_call(["pkg", "install", "-y"] + packages)
    elif is_ish():
        subprocess.check_call(["apk", "add", "--no-cache"] + packages)
    else:
        # Linux fallback
        subprocess.check_call(["sudo", "apt-get", "install", "-y"] + packages)

# ── checks ────────────────────────────────────────────────────────────────

def check_mpv():
    return shutil.which("mpv") is not None

def check_deno():
    return shutil.which("deno") is not None

def check_termux_api():
    return shutil.which("termux-notification") is not None

def check_curl():
    return shutil.which("curl") is not None

# ── main ──────────────────────────────────────────────────────────────────

def main():
    os.chdir(Path(__file__).parent)
    print()
    print("  biscuit — setup")
    print("  ───────────────")

    if is_termux():
        print("  platform: Android (Termux)")
    elif is_ish():
        print("  platform: iPhone (iSH)")
        # make sure python3 and basic tools are present on Alpine
        try:
            subprocess.check_call(["apk", "add", "--no-cache",
                                   "python3", "py3-pip", "curl", "mpv"])
            print("  ✓ base packages (python3, pip, curl, mpv)")
        except Exception as e:
            print(f"  ! apk install warning: {e}")
    else:
        print("  platform: Linux/Mac")

    print()

    # 1. Python deps
    # iSH/Alpine doesn't have pip by default — install it first
    if is_ish() and not shutil.which("pip3") and not shutil.which("pip"):
        print("  installing pip...")
        try:
            subprocess.check_call(["apk", "add", "--no-cache", "py3-pip"])
        except Exception as e:
            print(f"  ✗ pip install failed: {e}")
            print("  try manually: apk add py3-pip")
            sys.exit(1)

    missing = []
    for pkg in REQUIRED:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"  installing python deps: {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    print("  ✓ python deps")

    # 2. mpv
    if not check_mpv():
        print("  installing mpv...")
        try:
            if is_termux():
                pkg_install(["mpv"])
            elif is_ish():
                pkg_install(["mpv"])
            else:
                print("  install mpv manually: sudo apt install mpv")
                sys.exit(1)
        except Exception as e:
            print(f"  ✗ mpv install failed: {e}")
            sys.exit(1)
    print("  ✓ mpv")

    # 3. deno — required for YouTube JS challenge solving
    if not check_deno():
        print("  installing deno (required for YouTube playback)...")
        try:
            if is_termux():
                pkg_install(["deno"])
            elif is_ish():
                # deno not available on iSH/Alpine — use nodejs as fallback
                pkg_install(["nodejs", "npm"])
                print("  ! deno not available on iSH — using nodejs instead")
                print("    run: yt-dlp --js-runtimes nodejs to configure")
            else:
                # Linux: use official deno install script
                subprocess.check_call(
                    "curl -fsSL https://deno.land/install.sh | sh",
                    shell=True
                )
        except Exception as e:
            print(f"  ✗ deno install failed: {e}")
            print("  try manually: pkg install deno")
    else:
        print("  ✓ deno")

    # 4. curl — needed for notification button callbacks
    if not check_curl():
        print("  installing curl...")
        try:
            pkg_install(["curl"])
        except Exception as e:
            print(f"  ✗ curl install failed: {e}")
    else:
        print("  ✓ curl")

    # 5. termux-api — Android lockscreen controls (Termux only)
    if is_termux():
        if check_termux_api():
            print("  ✓ termux-api (lockscreen controls active)")
        else:
            print("  installing termux-api...")
            try:
                pkg_install(["termux-api"])
                print("  ✓ termux-api installed")
                print()
                print("  !! IMPORTANT: also install the Termux:API companion app")
                print("     from F-Droid for lockscreen controls to work:")
                print("     https://f-droid.org/packages/com.termux.api/")
            except Exception as e:
                print(f"  ✗ termux-api failed: {e}")
                print("  try: pkg install termux-api")

    # 6. cookies check
    print()
    cookies = next(
        (p for p in [
            Path("youtube.com_cookies.txt"),
            Path("cookies.txt"),
        ] if p.exists()),
        None
    )
    if cookies:
        print(f"  ✓ cookies found ({cookies}) — YouTube rate limiting bypassed")
    else:
        print("  ! no cookies file found")
        print("    without cookies, YouTube may block playback after a while.")
        print("    to fix:")
        print("    1. install 'cookies.txt' Firefox addon:")
        print("       https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/")
        print("    2. go to youtube.com (logged in)")
        print("    3. click the addon → Current Site → downloads cookies.txt")
        print("    4. put cookies.txt in this folder")

    print()
    print("  ───────────────")
    print("  all good. start with:")
    print("    python server.py")
    print()
    print("  then open http://127.0.0.1:5000 in your browser")
    print("  tip: add to home screen in Chrome/Firefox for app experience")
    print()

if __name__ == "__main__":
    main()
