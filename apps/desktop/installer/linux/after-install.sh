#!/bin/sh
set -eu

# Package configuration never downloads a runtime or touches a user's profile.
# Chromium needs its sandbox on Ubuntu installations restricting user namespaces.
if [ -f '/opt/${sanitizedProductName}/chrome-sandbox' ]; then
  chown root:root '/opt/${sanitizedProductName}/chrome-sandbox'
  chmod 4755 '/opt/${sanitizedProductName}/chrome-sandbox'
fi

if command -v update-mime-database >/dev/null 2>&1; then
  update-mime-database /usr/share/mime || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi

# electron-builder supplies the upstream Chromium userns profile. Ubuntu22
# lacks ABI4 support; install it only when the local parser accepts the policy.
if command -v apparmor_status >/dev/null 2>&1 && apparmor_status --enabled >/dev/null 2>&1; then
  policy='/opt/${sanitizedProductName}/resources/apparmor-profile'
  target='/etc/apparmor.d/${executable}'
  if apparmor_parser --skip-kernel-load --debug "$policy" >/dev/null 2>&1; then
    cp -f "$policy" "$target"
    if ! { [ -x /usr/bin/ischroot ] && /usr/bin/ischroot; }; then
      apparmor_parser --replace --write-cache --skip-read-cache "$target"
    fi
  fi
fi
