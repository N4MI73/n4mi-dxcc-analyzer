#!/bin/bash
# Build an .AppImage for n4mi-dxcc-analyzer.
# Usage: packaging/build-appimage.sh [--output-dir dist]
# The AppImage ships the app code + AppRun; python3 (>= 3.11) is expected on
# the host (venv + pip deps are created on first run under ~/.local/share).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="dist"
if [[ "${1:-}" == "--output-dir" ]]; then OUT_DIR="${2:-dist}"; fi
mkdir -p "$OUT_DIR"

VERSION="$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT'); from app.version import VERSION; print(VERSION)")"
PKG="n4mi-dxcc-analyzer"
WORK="$(mktemp -d /tmp/opencode/n4mi-appimage.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
APPDIR="$WORK/N4MI-DXCC-Analyzer.AppDir"
SRC="$APPDIR/usr/src/$PKG"

mkdir -p "$SRC" "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -r "$REPO_ROOT/app" "$REPO_ROOT/static" "$REPO_ROOT/images" "$SRC/"
cp "$REPO_ROOT/requirements.txt" "$REPO_ROOT/User_Guide.md" "$REPO_ROOT/README.md" "$REPO_ROOT/LICENSE" "$SRC/"
find "$SRC" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

cp "$REPO_ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
chmod 0755 "$APPDIR/AppRun"
cp "$REPO_ROOT/packaging/desktop/$PKG.desktop" "$APPDIR/$PKG.desktop"
cp "$REPO_ROOT/packaging/desktop/$PKG.desktop" "$APPDIR/usr/share/applications/$PKG.desktop"
cp "$REPO_ROOT/packaging/icons/$PKG.png" "$APPDIR/$PKG.png"
cp "$REPO_ROOT/packaging/icons/$PKG.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$PKG.png"
ln -sf "$PKG.desktop" "$APPDIR/.DirIcon" 2>/dev/null || cp "$REPO_ROOT/packaging/desktop/$PKG.desktop" "$APPDIR/.DirIcon"
ln -sf "$PKG.png" "$APPDIR/.DirIcon.png" 2>/dev/null || true

if ! command -v appimagetool >/dev/null 2>&1; then
  echo "appimagetool not found in PATH" >&2
  exit 1
fi

ARCH="$(uname -m)"
OUT="$OUT_DIR/N4MI-DXCC-Analyzer-${VERSION}-${ARCH}.AppImage"
# appimagetool needs FUSE or --appimage-extract; use ARCH env and allow no-fuse via env.
ARCH="$ARCH" appimagetool "$APPDIR" "$OUT"
chmod +x "$OUT"
echo "Built $OUT"
ls -la "$OUT"
