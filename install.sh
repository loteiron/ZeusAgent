#!/usr/bin/env bash
# Small stdin-safe bootstrap for the verified Linux release installer.
set -euo pipefail

installer_url='https://github.com/loteiron/ZeusAgent/releases/download/v0.22.0/install-linux.sh'
installer_sha256='b685d76d1413548754a09c082eb27dadf625a80b0767ae5229c0aa813f9bd661'

if [[ "${1:-}" == --help ]]; then
    printf '%s\n' 'Usage: bash install.sh [--user NAME] [--assets DIRECTORY] [--no-modify-path]' \
        'Installs the verified Linux x86_64 release. Root setup manages its own unprivileged account.'
    exit 0
fi

umask 077
bootstrap_dir=$(mktemp -d /tmp/zeus-bootstrap.XXXXXXXX)
trap 'rm -f -- "$bootstrap_dir/install-linux.sh"; rmdir -- "$bootstrap_dir"' EXIT
curl --fail --silent --show-error --location --retry 3 --connect-timeout 20 --max-time 180 \
    --proto '=https' --proto-redir '=https' --output "$bootstrap_dir/install-linux.sh" "$installer_url"
printf '%s  %s\n' "$installer_sha256" "$bootstrap_dir/install-linux.sh" | sha256sum --check --status || {
    printf '%s\n' 'ZeusAgent: installer checksum mismatch; nothing was executed.' >&2
    exit 2
}
bash "$bootstrap_dir/install-linux.sh" "$@"
