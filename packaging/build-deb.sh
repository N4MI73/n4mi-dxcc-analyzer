#!/bin/bash
# Build a .deb for n4mi-dxcc-analyzer (arch: all).
# Usage: packaging/build-deb.sh [--output-dir dist]
# Version is read from app/version.py so the header, Git tag and package agree.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${2:-dist}}"
if [[ "${1:-}" == "--output-dir" ]]; then OUT_DIR="${2:-dist}"; fi
mkdir -p "$OUT_DIR"

VERSION="$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT'); from app.version import VERSION; print(VERSION)")"
PKG="n4mi-dxcc-analyzer"
WORK="$(mktemp -d /tmp/opencode/n4mi-deb.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
ROOT="$WORK/$PKG"
APP_DIR="$ROOT/opt/$PKG"
BIN_DIR="$ROOT/usr/bin"
UNIT_DIR="$ROOT/lib/systemd/system"
DOC_DIR="$ROOT/usr/share/doc/$PKG"
DESK_DIR="$ROOT/usr/share/applications"
ICON_DIR="$ROOT/usr/share/icons/hicolor/256x256/apps"
DEBIAN="$ROOT/DEBIAN"

mkdir -p "$APP_DIR" "$BIN_DIR" "$UNIT_DIR" "$DOC_DIR" "$DESK_DIR" "$ICON_DIR" "$DEBIAN" "$ROOT/var/lib/$PKG"

# --- payload: code only (venv is created in postinst so the .deb stays small) ---
cp -r "$REPO_ROOT/app" "$APP_DIR/"
cp -r "$REPO_ROOT/static" "$APP_DIR/"
cp "$REPO_ROOT/requirements.txt" "$APP_DIR/"
cp "$REPO_ROOT/User_Guide.md" "$APP_DIR/"
cp "$REPO_ROOT/README.md" "$APP_DIR/" 2>/dev/null || true
cp "$REPO_ROOT/LICENSE" "$APP_DIR/"
cp -r "$REPO_ROOT/images" "$APP_DIR/" 2>/dev/null || true
find "$APP_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

install -m 0755 "$REPO_ROOT/packaging/launcher/$PKG" "$BIN_DIR/$PKG"
install -m 0644 "$REPO_ROOT/packaging/systemd/$PKG.service" "$UNIT_DIR/$PKG.service"
install -m 0644 "$REPO_ROOT/packaging/desktop/$PKG.desktop" "$DESK_DIR/$PKG.desktop"
install -m 0644 "$REPO_ROOT/packaging/icons/$PKG.png" "$ICON_DIR/$PKG.png"
install -m 0644 "$REPO_ROOT/packaging/icons/$PKG.svg" "$ICON_DIR/$PKG.svg" 2>/dev/null || true
install -m 0644 "$REPO_ROOT/LICENSE" "$DOC_DIR/copyright"
echo "$VERSION" > "$DOC_DIR/VERSION"
# Placeholder so the data dir exists with right perms after install (postinst chowns it).
touch "$ROOT/var/lib/$PKG/.keep"

cat > "$DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: hamradio
Priority: optional
Architecture: all
Maintainer: Dan Marshall, N4MI <n4mi@arrl.net>
Depends: python3 (>= 3.11), python3-venv, python3-pip, systemd
Description: N4MI DXCC Analyzer - what do I still need for DXCC?
 A small self-hosted app that reads the LoTW Award Credit Matrix
 and shows missing entities, needed band/mode slots and the full
 matrix. Serves on port 8086 (LAN-only). Data lives in
 /var/lib/n4mi-dxcc-analyzer.
EOF

cat > "$DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
PKG="n4mi-dxcc-analyzer"
APP_DIR="/opt/n4mi-dxcc-analyzer"
DATA_DIR="/var/lib/n4mi-dxcc-analyzer"

# Create a dedicated system user (no login, no home).
if ! getent group "$PKG" >/dev/null; then
  addgroup --system "$PKG" 2>/dev/null || groupadd -r "$PKG" || true
fi
if ! id "$PKG" >/dev/null 2>&1; then
  adduser --system --ingroup "$PKG" --no-create-home --home "$DATA_DIR" \
    --disabled-password --disabled-login --gecos "N4MI DXCC Analyzer" "$PKG" 2>/dev/null \
    || useradd -r -g "$PKG" -d "$DATA_DIR" -s /usr/sbin/nologin -c "N4MI DXCC Analyzer" "$PKG" || true
fi

mkdir -p "$DATA_DIR"
chown "$PKG:$PKG" "$DATA_DIR"
chmod 0750 "$DATA_DIR"

# Build/refresh the venv on install AND upgrade so pip deps track requirements.txt.
if [ ! -x "$APP_DIR/venv/bin/uvicorn" ]; then
  python3 -m venv "$APP_DIR/venv"
  "$APP_DIR/venv/bin/pip" install --upgrade pip
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
else
  "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" || true
fi
chown -R root:root "$APP_DIR"
chmod 0755 "$APP_DIR"

# systemd (skip gracefully inside Docker/chroot without systemd).
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
  systemctl enable "$PKG.service" || true
  if [ "${1:-}" = "configure" ]; then
    systemctl restart "$PKG.service" || systemctl start "$PKG.service" || true
  fi
else
  echo "$PKG: systemd not running; enable/start $PKG.service manually." >&2
fi
exit 0
POSTINST

cat > "$DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
PKG="n4mi-dxcc-analyzer"
if [ "$1" = "remove" ] || [ "$1" = "deconfigure" ]; then
  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl stop "$PKG.service" || true
    systemctl disable "$PKG.service" || true
  fi
fi
exit 0
PRERM

cat > "$DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
PKG="n4mi-dxcc-analyzer"
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
fi
# 'remove' keeps /var/lib/n4mi-dxcc-analyzer (history, marks, paper cards).
# 'purge' deletes it.
if [ "$1" = "purge" ]; then
  rm -rf "/var/lib/$PKG"
fi
exit 0
POSTRM

chmod 0755 "$DEBIAN/postinst" "$DEBIAN/prerm" "$DEBIAN/postrm"

DEB="$OUT_DIR/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$ROOT" "$DEB"
echo "Built $DEB"
dpkg-deb --info "$DEB"
