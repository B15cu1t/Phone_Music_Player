#!/data/data/com.termux/files/usr/bin/bash

cd "$(dirname "$0")"
echo ""
echo "  ● biscuit music player"
echo "  ─────────────────────────────"

if command -v termux-wake-lock &>/dev/null; then
  termux-wake-lock
  echo "  ✓ wake lock acquired"
else
  echo "  ! termux-wake-lock not found (install termux-api pkg for this)"
fi

if ! command -v mpv &>/dev/null; then
  echo ""
  echo "  ✗ mpv not found. Install it:"
  echo "    pkg install mpv"
  echo ""
  exit 1
fi
echo "  ✓ mpv ready"

if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
  echo "  ✗ python not found. Run: pkg install python"
  exit 1
fi
PY=$(command -v python3 || command -v python)

$PY -c "import flask" 2>/dev/null || {
  echo "  installing python deps..."
  $PY -m pip install -r requirements.txt -q --break-system-packages 2>/dev/null || \
  $PY -m pip install -r requirements.txt -q
}
echo "  ✓ deps ready"


echo "  updating yt-dlp..."
$PY -m pip install -U yt-dlp -q --break-system-packages 2>/dev/null || \
$PY -m pip install -U yt-dlp -q 2>/dev/null
echo "  ✓ yt-dlp up to date"

echo ""
echo "  open http://127.0.0.1:5000 in your browser"
echo "  add to home screen for app-like experience"
echo ""
echo "  ─────────────────────────────"

# Run server
$PY server.py
