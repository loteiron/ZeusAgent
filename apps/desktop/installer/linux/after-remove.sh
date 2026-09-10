#!/bin/sh
set -eu

# dpkg removes its own /usr/bin/zeus file. Do not edit PATH, alternatives, or
# user data. During an upgrade, the incoming package owns the shared policy.
case "$1" in remove|purge) ;; *) exit 0 ;; esac
policy='/etc/apparmor.d/${executable}'
if [ -f "$policy" ]; then
  if command -v apparmor_status >/dev/null 2>&1 && apparmor_status --enabled >/dev/null 2>&1; then
    if ! { [ -x /usr/bin/ischroot ] && /usr/bin/ischroot; }; then
      apparmor_parser --remove "$policy" || true
    fi
  fi
  rm -f "$policy"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi
