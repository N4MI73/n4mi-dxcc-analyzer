# Linux packaging for n4mi-dxcc-analyzer

Version comes from `app/version.py` in every builder — bump that one line
before tagging and the `.deb`, `.rpm`, `.desktop` and release assets agree.

| Builder | Output | Notes |
|---|---|---|
| `build-deb.sh [--output-dir dist]` | `dist/n4mi-dxcc-analyzer_<ver>_all.deb` | arch `all`; code in `/opt/n4mi-dxcc-analyzer`, venv created in `postinst`, unit in `/lib/systemd/system`, data in `/var/lib/n4mi-dxcc-analyzer`, user `n4mi-dxcc` |
| `build-rpm.sh [--output-dir dist]` | `dist/n4mi-dxcc-analyzer-<ver>-1.noarch.rpm` | same layout; plain scriptlets (no `systemd-rpm-macros` needed) |
| `build-appimage.sh [--output-dir dist]` | `dist/N4MI-DXCC-Analyzer-<ver>-x86_64.AppImage` | ships code + `AppRun`; host needs `python3 >= 3.11`; venv/data live in `~/.local/share/n4mi-dxcc-analyzer` |

Shared inputs: `systemd/n4mi-dxcc-analyzer.service`, `launcher/n4mi-dxcc-analyzer`
(`CONF`(`/usr/bin`), `desktop/n4mi-dxcc-analyzer.desktop`, `icons/` (SVG source,
256 px PNG), `rpm/n4mi-dxcc-analyzer.spec`.

`install.sh` (repo root) is the one-liner: tries the latest GitHub Release
asset for apt/dnf distros, else does a source install mirroring `postinst`.
CI: `.github/workflows/packages.yml` builds all three on `v*` tags, PRs
touching packaging, and manual dispatch; tag builds attach to the Release.
