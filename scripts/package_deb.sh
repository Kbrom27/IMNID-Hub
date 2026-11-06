#!/usr/bin/env bash
set -e

VERSION="1.0.0"
ARCH="amd64"
PKG_NAME="imnid-hub_${VERSION}_${ARCH}"
BUILD_ROOT="/tmp/${PKG_NAME}"

echo "Building Debian package for IMNID Hub v${VERSION} (${ARCH})..."

rm -rf "${BUILD_ROOT}"
mkdir -p "${BUILD_ROOT}/DEBIAN"
mkdir -p "${BUILD_ROOT}/opt/imnid-hub"
mkdir -p "${BUILD_ROOT}/usr/bin"
mkdir -p "${BUILD_ROOT}/usr/share/applications"
mkdir -p "${BUILD_ROOT}/usr/share/icons/hicolor/512x512/apps"
mkdir -p "${BUILD_ROOT}/lib/systemd/system"
mkdir -p "${BUILD_ROOT}/var/lib/imnid-hub/data"

# Control file
cat <<EOF > "${BUILD_ROOT}/DEBIAN/control"
Package: imnid-hub
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: IMNID Hub Team <support@imnid.org>
Description: Unified Health Information Interoperability & Data Platform
 IMNID Hub provides comprehensive tools for DHIS2, OpenMRS 3, SmartCare, and HMIS reporting.
EOF

# Postinst script: sets up symlinks and permissions
cat <<'EOF' > "${BUILD_ROOT}/DEBIAN/postinst"
#!/bin/bash
set -e
chmod +x /opt/imnid-hub/imnid-hub || true
chmod 777 /var/lib/imnid-hub/data || true
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi
echo "IMNID Hub installed successfully!"
echo "To start as a background service: sudo systemctl start imnid-hub"
echo "To launch from terminal or desktop menu: imnid-hub"
exit 0
EOF
chmod 755 "${BUILD_ROOT}/DEBIAN/postinst"

# Prerm script: stops service before upgrade/removal
cat <<'EOF' > "${BUILD_ROOT}/DEBIAN/prerm"
#!/bin/bash
set -e
if [ -d /run/systemd/system ]; then
    systemctl stop imnid-hub || true
    systemctl disable imnid-hub || true
fi
exit 0
EOF
chmod 755 "${BUILD_ROOT}/DEBIAN/prerm"

# Copy application files (dist/imnid-hub directory created by pyinstaller)
if [ -d "dist/imnid-hub" ]; then
    cp -r dist/imnid-hub/* "${BUILD_ROOT}/opt/imnid-hub/"
else
    echo "Error: dist/imnid-hub not found. Run PyInstaller first."
    exit 1
fi

# Desktop file & icons
cp imnid-hub.desktop "${BUILD_ROOT}/usr/share/applications/"
if [ -f "frontend/public/icon.jpeg" ]; then
    cp frontend/public/icon.jpeg "${BUILD_ROOT}/usr/share/icons/hicolor/512x512/apps/imnid-hub.jpg"
    cp frontend/public/icon.jpeg "${BUILD_ROOT}/opt/imnid-hub/icon.jpeg"
fi
if [ -f "frontend/public/IMNID_Hub_logo.png" ]; then
    cp frontend/public/IMNID_Hub_logo.png "${BUILD_ROOT}/opt/imnid-hub/logo.png"
fi

# Systemd service
cp imnid-hub.service "${BUILD_ROOT}/lib/systemd/system/"

# Symlink executable
ln -sf /opt/imnid-hub/imnid-hub "${BUILD_ROOT}/usr/bin/imnid-hub"

# Build deb package
dpkg-deb --build "${BUILD_ROOT}" "${PKG_NAME}.deb"
echo "Debian package created: ${PKG_NAME}.deb"

