#!/usr/bin/env bash
# Release template: stageLinuxInstaller fills immutable archive identities.
# Download the rendered install-linux.sh from the ZeusAgent GitHub release.
set -euo pipefail

VERSION='@@ZEUS_VERSION@@'
PACKAGE_FILE='@@ZEUS_PACKAGE_FILE@@'
PACKAGE_URL='@@ZEUS_PACKAGE_URL@@'
PACKAGE_SHA256='@@ZEUS_PACKAGE_SHA256@@'
NODE_FILE='@@ZEUS_NODE_FILE@@'
NODE_URL='@@ZEUS_NODE_URL@@'
NODE_SHA256='@@ZEUS_NODE_SHA256@@'
NODE_EXECUTABLE='@@ZEUS_NODE_EXECUTABLE@@'

fail() { printf 'ZeusAgent install: %s\n' "$*" >&2; exit 2; }
assets=''
modify_path=1
while (($#)); do
    case "$1" in
        --assets) (($# >= 2)) || fail '--assets requires a directory'; assets="$2"; shift 2 ;;
        --no-modify-path) modify_path=0; shift ;;
        --help) printf '%s\n' 'Usage: bash install-linux.sh [--assets <downloaded-release-directory>] [--no-modify-path]'; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done
[[ "$PACKAGE_SHA256" =~ ^[a-f0-9]{64}$ && "$NODE_SHA256" =~ ^[a-f0-9]{64}$ ]] || fail 'Use the rendered installer attached to a GitHub release.'
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail 'This release requires Linux x86_64.'
[[ "$(id -u)" != 0 ]] || fail 'Run as your normal user, without sudo. Only system dependency installation uses sudo.'
[[ -n "${HOME:-}" && "$HOME" == /* && "$HOME" != *$'\n'* ]] || fail 'HOME must be an absolute directory.'
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
[[ "$data_home" == /* && "$data_home" != *$'\n'* ]] || fail 'XDG_DATA_HOME must be an absolute directory.'
if [[ -n "$assets" ]]; then
    [[ -d "$assets" ]] || fail 'The downloaded release directory does not exist.'
    assets="$(cd -- "$assets" && pwd -P)"
fi

missing=()
for command in curl tar xz sha256sum git rg; do
    command -v "$command" >/dev/null || missing+=("$command")
done
if ((${#missing[@]})); then
    command -v apt-get >/dev/null && command -v sudo >/dev/null || fail 'Install curl, tar, xz-utils, coreutils, git and ripgrep, then retry.'
    printf '%s\n' 'Installing Ubuntu system dependencies with sudo; ZeusAgent itself stays in your user directory.'
    sudo apt-get update
    sudo apt-get install --yes ca-certificates curl tar xz-utils coreutils git ripgrep
fi

base="$data_home/ZeusAgent/cli"
bin="$HOME/.local/bin"
launcher="$bin/zeus"
[[ ! -L "$base" && ! -L "$launcher" ]] || fail 'Refusing to replace a symbolic link at the managed CLI location.'
mkdir -p -- "$base/releases" "$bin"
launcher_identity() {
    [[ ! -L "$launcher" ]] || fail 'The CLI launcher changed to a symbolic link during setup.'
    if [[ -e "$launcher" ]]; then sha256sum "$launcher"; else printf '%s\n' absent; fi
}
initial_launcher="$(launcher_identity)"
if [[ -e "$launcher" ]] && ! grep -Fqx '# ZeusAgent managed CLI launcher' "$launcher"; then
    fail "A different zeus command already exists at $launcher; it was preserved."
fi
lock="$base/install.lock"
mkdir -- "$lock" 2>/dev/null || fail "Another install is active or was interrupted. Inspect and remove only $lock after stopping it."
scratch=''
cleanup() {
    if [[ -n "$scratch" && "$scratch" == "$base"/.install.* ]]; then rm -rf -- "$scratch"; fi
    rmdir -- "$lock" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
scratch="$(mktemp -d "$base/.install.XXXXXXXX")"
download() {
    local filename="$1" url="$2" expected="$3" target="$scratch/$1"
    if [[ -n "$assets" ]]; then
        [[ -f "$assets/$filename" ]] || fail "Missing downloaded archive: $filename"
        cp -- "$assets/$filename" "$target"
    else
        curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --retry 2 --output "$target" "$url"
    fi
    local actual
    actual="$(sha256sum "$target")"
    [[ "${actual%% *}" == "$expected" ]] || fail "Checksum mismatch for $filename. Nothing from this archive was executed."
}
release="$base/releases/$VERSION-${PACKAGE_SHA256:0:12}"
receipt="$VERSION $PACKAGE_SHA256 $NODE_SHA256"
if [[ -e "$release" ]]; then
    [[ ! -L "$release" && -f "$release/.zeus-cli-receipt" ]] || fail 'Existing CLI release is not owned by this installer.'
    [[ "$(cat "$release/.zeus-cli-receipt")" == "$receipt" ]] || fail 'Existing CLI release identity differs; it was preserved.'
else
    download "$PACKAGE_FILE" "$PACKAGE_URL" "$PACKAGE_SHA256"
    download "$NODE_FILE" "$NODE_URL" "$NODE_SHA256"
    mkdir -- "$scratch/release"
    # Both archives have already passed the release-pinned digest check.
    tar --extract --gzip --file "$scratch/$PACKAGE_FILE" --directory "$scratch/release" --no-same-owner
    tar --extract --xz --file "$scratch/$NODE_FILE" --directory "$scratch/release" --no-same-owner
    [[ -f "$scratch/release/package/bin/zeus.mjs" && -x "$scratch/release/$NODE_EXECUTABLE" ]] || fail 'Release archives do not contain the expected launcher and Node runtime.'
    if [[ -n "$assets" ]]; then
        # Offline/prepublication installs reuse downloaded release assets. The
        # runtime helper independently validates each digest before extraction.
        "$scratch/release/$NODE_EXECUTABLE" --input-type=module - "$scratch/release/package/linux-runtime-manifest.json" <<'NODE' > "$scratch/runtime-assets"
import {readFileSync} from 'node:fs';
const manifest = JSON.parse(readFileSync(process.argv[2], 'utf8'));
for (const asset of [manifest.source, manifest.uv, ...Object.values(manifest.tools || {})].filter(Boolean)) {
    if (!/^[A-Za-z0-9_.-]+$/.test(asset.file) || asset.file === '.' || asset.file === '..') throw new Error('Invalid runtime asset name');
    console.log(asset.file);
}
NODE
        while IFS= read -r filename; do
            if [[ -f "$assets/$filename" ]]; then cp -- "$assets/$filename" "$scratch/release/package/$filename"; fi
        done < "$scratch/runtime-assets"
    fi
    printf '%s\n' "$receipt" > "$scratch/release/.zeus-cli-receipt"
    mv -- "$scratch/release" "$release"
fi
[[ -x "$release/$NODE_EXECUTABLE" && -f "$release/package/bin/zeus.mjs" ]] || fail 'Installed CLI files are missing; preserve your profile and reinstall the CLI release.'
# printf %q quotes each absolute path for Bash; no user's argument becomes code.
{
    printf '%s\n' '#!/usr/bin/env bash' '# ZeusAgent managed CLI launcher'
    printf 'exec %q %q "$@"\n' "$release/$NODE_EXECUTABLE" "$release/package/bin/zeus.mjs"
} > "$scratch/zeus"
chmod 755 "$scratch/zeus"
[[ "$(launcher_identity)" == "$initial_launcher" ]] || fail 'The zeus launcher changed during setup; your new command was preserved. Run the installer again after reviewing it.'
mv -f -- "$scratch/zeus" "$launcher"
if ((modify_path)); then
    block='# >>> ZeusAgent CLI PATH >>>
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
# <<< ZeusAgent CLI PATH <<<'
    for profile in "$HOME/.profile" "$HOME/.bashrc" "$HOME/.zshrc"; do
        [[ "$profile" != "$HOME/.zshrc" || -e "$profile" ]] || continue
        if [[ -L "$profile" || ( -e "$profile" && ! -f "$profile" ) ]]; then
            printf 'Preserved custom profile %s; add ~/.local/bin to PATH manually.\n' "$profile"
            continue
        fi
        if ! grep -Fqx '# >>> ZeusAgent CLI PATH >>>' "$profile" 2>/dev/null; then
            printf '\n%s\n' "$block" >> "$profile"
        fi
    done
fi
printf '%s\n' 'Preparing the verified Python environment. The first launch can take a few minutes.'
"$launcher" --version
printf '\nZeusAgent %s installed. Reopen your terminal and run: zeus setup\n' "$VERSION"
printf 'To use this terminal immediately: export PATH="$HOME/.local/bin:$PATH"\n'
