#!/data/data/com.termux/files/usr/bin/bash
# start.sh — launch Biscuit Music Player in Termux
# Run this from the project folder: bash start.sh

cd "$(dirname "$0")"

echo ""
echo "  ● biscuit music player"
echo "  ─────────────────────────────"

# Termux wake lock so CPU keeps running when screen is off
if command -v termux-wake-lock &>/dev/null; then
  termux-wake-lock
  echo "  ✓ wake lock acquired"
else
  echo "  ! termux-wake-lock not found (install termux-api pkg for this)"
fi

# Check mpv
if ! command -v mpv &>/dev/null; then
  echo ""
  echo "  ✗ mpv not found. Install it:"
  echo "    pkg install mpv"
  echo ""
  exit 1
fi
echo "  ✓ mpv ready"

# Check python
if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
  echo "  ✗ python not found. Run: pkg install python"
  exit 1
fi

PY=$(command -v python3 || command -v python)

# Install pip deps if needed
$PY -c "import flask" 2>/dev/null || {
  echo "  installing python deps..."
  $PY -m pip install -r requirements.txt -q
}

echo "  ✓ deps ready"
echo ""
echo "  open http://127.0.0.1:5000 in your browser"
echo "  add to home screen for app-like experience"
echo ""
echo "  ─────────────────────────────"

# Run server
$PY server.py
