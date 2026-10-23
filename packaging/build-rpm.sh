#!/bin/bash
# Build an .rpm for n4mi-dxcc-analyzer (noarch).
# Usage: packaging/build-rpm.sh [--output-dir dist]
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="dist"
if [[ "${1:-}" == "--output-dir" ]]; then OUT_DIR="${2:-dist}"; fi
mkdir -p "$OUT_DIR"

VERSION="$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT'); from app.version import VERSION; print(VERSION)")"
PKG="n4mi-dxcc-analyzer"
TOPDIR="$(mktemp -d /tmp/opencode/n4mi-rpm.XXXXXX)"
trap 'rm -rf "$TOPDIR"' EXIT
mkdir -p "$TOPDIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Source tarball the spec expects: %{name}-%{version}.tar.gz containing
# app/, static/, images/, requirements.txt, README, User_Guide, LICENSE, packaging/.
STAGE="$TOPDIR/STAGE/$PKG-$VERSION"
mkdir -p "$STAGE"
cp -r "$REPO_ROOT/app" "$REPO_ROOT/static" "$REPO_ROOT/images" "$STAGE/" 2>/dev/null || true
cp "$REPO_ROOT/requirements.txt" "$REPO_ROOT/User_Guide.md" "$REPO_ROOT/README.md" "$REPO_ROOT/LICENSE" "$STAGE/"
cp -r "$REPO_ROOT/packaging" "$STAGE/"
find "$STAGE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
tar -czf "$TOPDIR/SOURCES/$PKG-$VERSION.tar.gz" -C "$TOPDIR/STAGE" "$PKG-$VERSION"

sed "s/^Version:.*/Version:        $VERSION/" "$REPO_ROOT/packaging/rpm/$PKG.spec" > "$TOPDIR/SPECS/$PKG.spec"

rpmbuild --define "_topdir $TOPDIR" -bb "$TOPDIR/SPECS/$PKG.spec"
RPM="$(find "$TOPDIR/RPMS" -name '*.rpm' | head -n 1)"
cp "$RPM" "$OUT_DIR/"
echo "Built $OUT_DIR/$(basename "$RPM")"
rpm -qlp "$OUT_DIR/$(basename "$RPM")"
