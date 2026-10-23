Name:           n4mi-dxcc-analyzer
Version:        0.0.0
Release:        1%{?dist}
Summary:        N4MI DXCC Analyzer - what do I still need for DXCC?
License:        MIT
URL:            https://github.com/N4MI73/n4mi-dxcc-analyzer
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.11, systemd
# NOTE: deliberately no systemd-rpm-macros BuildRequires so the package builds
# on distros without those macros; unit handling is done with plain scriptlets.

%description
A small self-hosted app that reads the LoTW Award Credit Matrix and shows
missing entities, needed band/mode slots and the full matrix. Serves on
port 8086 (LAN-only). Data lives in /var/lib/n4mi-dxcc-analyzer.

%prep
%setup -q -n %{name}-%{version}

%build
# No compiled code; venv is created in %post.

%install
APP_DIR="%{buildroot}/opt/%{name}"
install -d "$APP_DIR" "%{buildroot}/usr/bin" \
  "%{buildroot}/usr/lib/systemd/system" \
  "%{buildroot}/usr/share/applications" \
  "%{buildroot}/usr/share/icons/hicolor/256x256/apps" \
  "%{buildroot}/usr/share/doc/%{name}" \
  "%{buildroot}/var/lib/%{name}"
cp -r app static images "$APP_DIR/"
cp requirements.txt User_Guide.md README.md LICENSE "$APP_DIR/"
rm -rf "$APP_DIR"/app/__pycache__
install -m 0755 packaging/launcher/%{name} "%{buildroot}/usr/bin/%{name}"
install -m 0644 packaging/systemd/%{name}.service "%{buildroot}/usr/lib/systemd/system/%{name}.service"
install -m 0644 packaging/desktop/%{name}.desktop "%{buildroot}/usr/share/applications/%{name}.desktop"
install -m 0644 packaging/icons/%{name}.png "%{buildroot}/usr/share/icons/hicolor/256x256/apps/%{name}.png"
install -m 0644 LICENSE "%{buildroot}/usr/share/doc/%{name}/copyright"
echo "%{version}" > "%{buildroot}/usr/share/doc/%{name}/VERSION"
touch "%{buildroot}/var/lib/%{name}/.keep"

%files
/opt/%{name}/
/usr/bin/%{name}
/usr/lib/systemd/system/%{name}.service
/usr/share/applications/%{name}.desktop
/usr/share/icons/hicolor/256x256/apps/%{name}.png
/usr/share/doc/%{name}/
%ghost /var/lib/%{name}/.keep

%pre
getent group n4mi-dxcc >/dev/null || groupadd -r n4mi-dxcc || :
id n4mi-dxcc >/dev/null 2>&1 || useradd -r -g n4mi-dxcc -d /var/lib/n4mi-dxcc-analyzer -s /sbin/nologin -c "N4MI DXCC Analyzer" n4mi-dxcc || :

%post
mkdir -p /var/lib/n4mi-dxcc-analyzer
chown n4mi-dxcc:n4mi-dxcc /var/lib/n4mi-dxcc-analyzer
chmod 0750 /var/lib/n4mi-dxcc-analyzer
if [ ! -x /opt/n4mi-dxcc-analyzer/venv/bin/uvicorn ]; then
  python3 -m venv /opt/n4mi-dxcc-analyzer/venv
  /opt/n4mi-dxcc-analyzer/venv/bin/pip install --upgrade pip
  /opt/n4mi-dxcc-analyzer/venv/bin/pip install -r /opt/n4mi-dxcc-analyzer/requirements.txt
else
  /opt/n4mi-dxcc-analyzer/venv/bin/pip install -r /opt/n4mi-dxcc-analyzer/requirements.txt || true
fi
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
  systemctl enable n4mi-dxcc-analyzer.service || true
  systemctl restart n4mi-dxcc-analyzer.service || systemctl start n4mi-dxcc-analyzer.service || true
fi

%preun
if [ "$1" = "0" ]; then
  if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl stop n4mi-dxcc-analyzer.service || true
    systemctl disable n4mi-dxcc-analyzer.service || true
  fi
fi

%postun
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
fi
