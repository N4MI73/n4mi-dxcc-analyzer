#!/bin/bash
# N4MI DXCC Analyzer - one-liner installer for Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/N4MI73/n4mi-dxcc-analyzer/main/install.sh | sudo bash
#
# What it does:
#   1. If --deb/--rpm is given (or a matching GitHub Release asset exists and
#      the distro uses apt/dnf), installs the native package.
#   2. Otherwise installs from source: system python3 + venv in
#      /opt/n4mi-dxcc-analyzer, launcher in /usr/bin, systemd unit, data dir
#      in /var/lib/n4mi-dxcc-analyzer, service enabled+started on port 8086.
#
# Env overrides: REPO, BRANCH, PORT, HOST, DATA_DIR, INSTALL_DIR, NO_START=1
# Args: --help, --dry-run, --from-source, --deb URL|path, --rpm URL|path,
#       --appimage URL|path, --port N, --no-start, --uninstall [--purge]
set -euo pipefail
REPO="${REPO:-N4MI73/n4mi-dxcc-analyzer}"
BRANCH="${BRANCH:-main}"
PORT="${PORT:-8086}"
HOST="${HOST:-0.0.0.0}"
DATA_DIR="${DATA_DIR:-/var/lib/n4mi-dxcc-analyzer}"
INSTALL_DIR="${INSTALL_DIR:-/opt/n4mi-dxcc-analyzer}"
PKG="n4mi-dxcc-analyzer"
DRY_RUN=0
FROM_SOURCE=0
DEB_SRC=""
RPM_SRC=""
APPIMAGE_SRC=""
NO_START="${NO_START:-0}"
UNINSTALL=0
PURGE=0

log() { echo "[install] $*"; }
run() { if [ "$DRY_RUN" = "1" ]; then echo "+ $*"; else eval "$*"; fi; }
need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root (or with sudo): curl ... | sudo bash" >&2
    exit 1
  fi
}

usage() {
  sed -n '2,20p' "$0"
  echo "Options: [--from-source] [--deb URL] [--rpm URL] [--appimage URL]"
  echo "         [--port N] [--no-start] [--dry-run] [--uninstall [--purge]]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --from-source) FROM_SOURCE=1; shift ;;
    --deb) DEB_SRC="$2"; shift 2 ;;
    --rpm) RPM_SRC="$2"; shift 2 ;;
    --appimage) APPIMAGE_SRC="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --no-start) NO_START=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --purge) PURGE=1; shift ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }
os_id() { . /etc/os-release 2>/dev/null; echo "${ID:-unknown}"; }

uninstall() {
  need_root
  log "Stopping $PKG ..."
  run "systemctl stop $PKG.service || true"
  run "systemctl disable $PKG.service || true"
  run "rm -f /lib/systemd/system/$PKG.service /usr/lib/systemd/system/$PKG.service /etc/systemd/system/$PKG.service"
  run "rm -f /usr/bin/$PKG /usr/share/applications/$PKG.desktop /usr/share/icons/hicolor/256x256/apps/$PKG.png"
  run "systemctl daemon-reload || true"
  # dpkg/rpm remove if they own it (keeps $DATA_DIR unless --purge, like postrm).
  if have dpkg && dpkg -s "$PKG" >/dev/null 2>&1; then
    if [ "$PURGE" = "1" ]; then run "apt-get purge -y $PKG"; else run "apt-get remove -y $PKG"; fi
  elif have rpm && rpm -q "$PKG" >/dev/null 2>&1; then
    if [ "$PURGE" = "1" ]; then run "rpm -e $PKG || dnf remove -y $PKG"; else run "rpm -e $PKG || dnf remove -y $PKG"; fi
  else
    run "rm -rf $INSTALL_DIR"
    if getent passwd "$PKG" >/dev/null; then run "userdel $PKG || true"; fi
  fi
  if [ "$PURGE" = "1" ]; then
    run "rm -rf $DATA_DIR"
    log "Purged $DATA_DIR"
  else
    log "Kept data in $DATA_DIR (re-run with --purge to delete)"
  fi
  log "Uninstalled."
  exit 0
}
[ "$UNINSTALL" = "1" ] && uninstall

need_root
log "N4MI DXCC Analyzer installer (repo=$REPO branch=$BRANCH port=$PORT)"

# --- 1. explicit package paths -------------------------------------------------
install_file() { # kind path-or-url
  src="$2"
  tmp="$src"
  if echo "$src" | grep -qE '^https?://'; then
    tmp="/tmp/opencode/$PKG-install.$(basename "$src")"
    mkdir -p /tmp/opencode
    log "Downloading $src ..."
    if [ "$DRY_RUN" = "1" ]; then echo "+ curl -fsSL -o $tmp $src"; else curl -fsSL -o "$tmp" "$src"; fi
  fi
  case "$1" in
    deb) run "apt-get update && apt-get install -y $tmp" ;;
    rpm)
      if have dnf; then run "dnf install -y $tmp"
      elif have yum; then run "yum install -y $tmp"
      elif have zypper; then run "zypper --non-interactive install $tmp"
      else run "rpm -Uvh $tmp"; fi ;;
    appimage)
      run "install -m 0755 $tmp /usr/local/bin/$PKG.AppImage"
      log "AppImage installed to /usr/local/bin/$PKG.AppImage; run it (no systemd unit)."; exit 0 ;;
  esac
  exit 0
}
[ -n "$DEB_SRC" ] && install_file deb "$DEB_SRC"
[ -n "$RPM_SRC" ] && install_file rpm "$RPM_SRC"
[ -n "$APPIMAGE_SRC" ] && install_file appimage "$APPIMAGE_SRC"

# --- 2. try latest GitHub Release asset matching this distro -------------------
if [ "$FROM_SOURCE" = "0" ] && have curl; then
  LATEST_JSON="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null || true)"
  if echo "$LATEST_JSON" | grep -q '"assets"'; then
    ID="$(os_id)"
    case "$ID" in
      ubuntu|debian|linuxmint|pop|raspbian)
        URL="$(echo "$LATEST_JSON" | grep -oE '"browser_download_url": *"[^"]*\.deb"' | head -n 1 | cut -d'"' -f4 || true)"
        if [ -n "${URL:-}" ] && have apt-get; then log "Found release .deb; installing..."; install_file deb "$URL"; fi ;;
      fedora|rhel|centos|rocky|alma|opensuse*|suse)
        URL="$(echo "$LATEST_JSON" | grep -oE '"browser_download_url": *"[^"]*\.rpm"' | head -n 1 | cut -d'"' -f4 || true)"
        if [ -n "${URL:-}" ]; then log "Found release .rpm; installing..."; install_file rpm "$URL"; fi ;;
    esac
  fi
  log "No usable release asset (or not apt/rpm distro); falling back to source install."
fi

# --- 3. source install ----------------------------------------------------------
log "Installing from source into $INSTALL_DIR ..."
if have apt-get; then
  run "apt-get update"
  run "apt-get install -y python3 python3-venv python3-pip git curl systemd"
elif have dnf; then
  run "dnf install -y python3 git curl systemd"
elif have yum; then
  run "yum install -y python3 git curl systemd"
elif have pacman; then
  run "pacman -Sy --noconfirm python git curl systemd"
elif have zypper; then
  run "zypper --non-interactive install python3 git curl systemd"
elif have apk; then
  run "apk add python3 py3-venv py3-pip git curl"
else
  echo "No supported package manager (apt/dnf/yum/pacman/zypper/apk). Install python3 (>=3.11), git and systemd manually." >&2
  exit 1
fi

getent group "$PKG" >/dev/null || run "groupadd -r $PKG || addgroup --system $PKG || true"
id "$PKG" >/dev/null 2>&1 || run "useradd -r -g $PKG -d $DATA_DIR -s /usr/sbin/nologin -c 'N4MI DXCC Analyzer' $PKG || adduser --system --ingroup $PKG --no-create-home --home $DATA_DIR --disabled-login --gecos 'N4MI DXCC Analyzer' $PKG || true"

TMP_CLONE="$(mktemp -d /tmp/opencode/n4mi-src.XXXXXX)"
if [ "$DRY_RUN" = "1" ]; then
  echo "+ git clone --depth 1 --branch $BRANCH https://github.com/$REPO $TMP_CLONE"
else
  rm -rf "$TMP_CLONE"; git clone --depth 1 --branch "$BRANCH" "https://github.com/$REPO" "$TMP_CLONE"
fi
run "mkdir -p $INSTALL_DIR $DATA_DIR"
run "cp -r $TMP_CLONE/app $TMP_CLONE/static $TMP_CLONE/images $INSTALL_DIR/ 2>/dev/null || cp -r $TMP_CLONE/app $TMP_CLONE/static $INSTALL_DIR/"
run "cp $TMP_CLONE/requirements.txt $TMP_CLONE/User_Guide.md $TMP_CLONE/README.md $TMP_CLONE/LICENSE $INSTALL_DIR/"
run "cp $TMP_CLONE/packaging/launcher/$PKG /usr/bin/$PKG && chmod 0755 /usr/bin/$PKG"
run "cp $TMP_CLONE/packaging/systemd/$PKG.service /lib/systemd/system/$PKG.service || cp $TMP_CLONE/packaging/systemd/$PKG.service /etc/systemd/system/$PKG.service"
run "cp $TMP_CLONE/packaging/desktop/$PKG.desktop /usr/share/applications/ 2>/dev/null || true"
run "mkdir -p /usr/share/icons/hicolor/256x256/apps && cp $TMP_CLONE/packaging/icons/$PKG.png /usr/share/icons/hicolor/256x256/apps/ 2>/dev/null || true"
run "rm -rf $TMP_CLONE"
run "chown -R root:root $INSTALL_DIR && chmod 0755 $INSTALL_DIR"
run "chown $PKG:$PKG $DATA_DIR && chmod 0750 $DATA_DIR"

if [ ! -x "$INSTALL_DIR/venv/bin/uvicorn" ]; then
  run "python3 -m venv $INSTALL_DIR/venv"
  run "$INSTALL_DIR/venv/bin/pip install --upgrade pip"
fi
run "$INSTALL_DIR/venv/bin/pip install -r $INSTALL_DIR/requirements.txt"

# Apply chosen port to the unit (default 8086 in the shipped file).
if [ "$PORT" != "8086" ]; then
  run "sed -i 's/^Environment=PORT=.*/Environment=PORT=$PORT/' /lib/systemd/system/$PKG.service 2>/dev/null || sed -i 's/^Environment=PORT=.*/Environment=PORT=$PORT/' /etc/systemd/system/$PKG.service"
fi
run "systemctl daemon-reload || true"
run "systemctl enable $PKG.service || true"
if [ "$NO_START" = "1" ]; then
  log "Installed (not started: NO_START=1). Start with: systemctl start $PKG"
else
  run "systemctl restart $PKG.service || systemctl start $PKG.service || true"
  sleep 2
  if curl -fsS "http://127.0.0.1:$PORT/healthz" 2>/dev/null | grep -q '"ok"'; then
    log "OK: http://$(hostname -f 2>/dev/null || hostname):$PORT/ (health: /healthz)"
  else
    log "Service installed; health check did not answer yet - see: journalctl -u $PKG -e"
    log "Open http://<this-host>:$PORT/ once it is up. Data: $DATA_DIR"
  fi
fi
