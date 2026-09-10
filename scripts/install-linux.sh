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
install_user=''
while (($#)); do
    case "$1" in
        --assets) (($# >= 2)) || fail '--assets requires a directory'; assets="$2"; shift 2 ;;
        --user) (($# >= 2)) || fail '--user requires an existing ordinary user'; install_user="$2"; shift 2 ;;
        --no-modify-path) modify_path=0; shift ;;
        --help) printf '%s\n' 'Usage: bash install-linux.sh [--user <existing-user>] [--assets <downloaded-release-directory>] [--no-modify-path]' 'Root installs automatically for the sudo user or a dedicated, unprivileged zeususer account.'; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done
[[ "$PACKAGE_SHA256" =~ ^[a-f0-9]{64}$ && "$NODE_SHA256" =~ ^[a-f0-9]{64}$ ]] || fail 'Use the rendered installer attached to a GitHub release.'
# Never resolve privileged setup commands through a root-only npm/Node directory.
root_command=''
if ((EUID == 0)); then
    root_command="$(type -P zeus || true)"
    export PATH=/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
fi
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || fail 'This release requires Linux x86_64.'

install_dependencies() {
    local missing=() command
    for command in curl tar xz sha256sum git rg; do
        command -v "$command" >/dev/null || missing+=("$command")
    done
    if ((EUID == 0)); then
        for command in runuser useradd; do
            command -v "$command" >/dev/null || missing+=("$command")
        done
    fi
    ((${#missing[@]})) || return 0
    command -v apt-get >/dev/null || fail 'Install curl, tar, xz-utils, coreutils, git and ripgrep, then retry.'
    local elevate=()
    if ((EUID != 0)); then
        command -v sudo >/dev/null || fail 'Missing system dependencies. Run this installer once as root; it will prepare your unprivileged account automatically.'
        elevate=(sudo)
    fi
    printf '%s\n' 'Installing Ubuntu system dependencies; ZeusAgent runs in an unprivileged user account.'
    "${elevate[@]}" apt-get update
    "${elevate[@]}" apt-get install --yes ca-certificates curl tar xz-utils coreutils git ripgrep util-linux passwd
}

if ((EUID == 0)); then
    # The privileged portion installs only OS packages and a dispatcher. The
    # release archives, Node and Python are always prepared as the target user.
    umask 022
    install_dependencies
    ordinary_user() {
        [[ "$1" =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || return 1
        local entry name password uid gid description home shell
        entry="$(getent passwd "$1")" || return 1
        IFS=: read -r name password uid gid description home shell <<< "$entry"
        [[ "$name" == "$1" && "$uid" =~ ^[0-9]+$ ]] && ((uid >= 1000 && uid < 65534)) || return 1
        [[ "$home" == /* && "$home" != / && "$home" != /root && "$home" != *$'\n'* && -d "$home" && ! -L "$home" ]] || return 1
        [[ "$(stat -c %u -- "$home")" == "$uid" ]] || return 1
        target_home="$home"
        target_uid="$uid"
    }
    if [[ -n "$install_user" ]]; then
        ordinary_user "$install_user" || fail '--user must name an existing ordinary user with its own home directory.'
    elif [[ -n "${SUDO_USER:-}" ]] && ordinary_user "$SUDO_USER"; then
        install_user="$SUDO_USER"
    else
        install_user=zeususer
        if ! getent passwd "$install_user" >/dev/null; then
            [[ ! -e /home/zeususer && ! -L /home/zeususer ]] || fail '/home/zeususer already exists without its account; it was preserved. Use --user with an existing user.'
            useradd --create-home --home-dir /home/zeususer --shell /bin/bash --password '!' "$install_user"
        fi
        ordinary_user "$install_user" || fail 'The zeususer account is not an ordinary user with its own home. Use --user with an existing user.'
    fi
    global_launcher=/usr/local/bin/zeus
    [[ ! -L /usr/local && ! -L /usr/local/bin ]] || fail 'Refusing to install through a symbolic link at /usr/local/bin.'
    mkdir -p -- /usr/local/bin
    safe_root_directory() {
        [[ "$(stat -c %u -- "$1")" == 0 ]] && (( (8#$(stat -c %a -- "$1") & 0022) == 0 ))
    }
    for directory in /usr/local /usr/local/bin; do
        safe_root_directory "$directory" || fail "$directory must be root-owned and not writable by other users."
    done
    global_identity() {
        if [[ -L "$global_launcher" ]]; then
            printf 'link:%s\n' "$(readlink -- "$global_launcher")"
        elif [[ -f "$global_launcher" ]]; then
            sha256sum "$global_launcher"
        elif [[ -e "$global_launcher" ]]; then
            fail "A different zeus command exists at $global_launcher; it was preserved."
        else printf '%s\n' absent; fi
    }
    initial_global="$(global_identity)"
    preserve_npm=0
    if [[ -L "$global_launcher" ]]; then
        npm_target="$(readlink -f -- "$global_launcher")" || fail 'The existing zeus symlink could not be resolved; it was preserved.'
        [[ "$npm_target" == */@loteiron/zeus-agent/bin/zeus.mjs ]] || fail 'An unrelated zeus symlink already exists in /usr/local/bin; it was preserved.'
        preserve_npm=1
    elif [[ -e "$global_launcher" ]]; then
        [[ "$(stat -c %u -- "$global_launcher")" == 0 ]] && grep -Fqx '# ZeusAgent managed user dispatcher' "$global_launcher" || fail 'An unrelated zeus command already exists in /usr/local/bin; it was preserved.'
    fi
    # A root npm/NVM bin can precede /usr/local/bin, even in a shell's command
    # cache. Adopt only its verified, root-owned Zeus symlink, never its Node.
    shadow_launcher=''
    shadow_parent=''
    shadow_identity=''
    if [[ -n "$root_command" ]]; then
        [[ "$root_command" == /* && "$root_command" != *$'\n'* ]] || fail 'A relative zeus command shadows /usr/local/bin; it was preserved. Use an absolute system PATH and retry.'
        command_parent="$(cd -- "$(dirname -- "$root_command")" && pwd -P)"
        root_command="$command_parent/$(basename -- "$root_command")"
        if [[ "$root_command" != "$global_launcher" ]]; then
            [[ -L "$root_command" && "$(stat -c %u -- "$root_command")" == 0 ]] || fail "An unrelated or user-owned command at $root_command shadows Zeus; it was preserved."
            directory="$command_parent"
            while :; do
                safe_root_directory "$directory" || fail "The shadowing command directory $directory is not exclusively root-managed; it was preserved."
                [[ "$directory" != / ]] || break
                directory="$(dirname -- "$directory")"
            done
            resolved_command="$(readlink -f -- "$root_command")" || fail 'The shadowing Zeus command could not be resolved; it was preserved.'
            if [[ "$resolved_command" != "$global_launcher" ]]; then
                [[ "$resolved_command" == */@loteiron/zeus-agent/bin/zeus.mjs ]] || fail "An unrelated command at $root_command shadows Zeus; it was preserved."
                shadow_launcher="$root_command"
                shadow_parent="$command_parent"
                shadow_identity="$(readlink -- "$root_command")"
            fi
        fi
    fi
    root_stage=''
    dispatcher_stage=''
    npm_backup=''
    shadow_backup=''
    shadow_stage=''
    cleanup_root() {
        if [[ -n "$root_stage" && "$root_stage" == /tmp/zeus-installer.* ]]; then rm -rf -- "$root_stage"; fi
        if [[ -n "$dispatcher_stage" && "$dispatcher_stage" == /usr/local/bin/.zeus-dispatch.* ]]; then rm -f -- "$dispatcher_stage"; fi
        if [[ -n "$npm_backup" && ! -e "$global_launcher" && ! -L "$global_launcher" ]]; then mv -T -- "$npm_backup" "$global_launcher"; fi
        if [[ -n "$shadow_stage" && "$shadow_stage" == "$shadow_parent"/.zeus-link.* ]]; then rm -f -- "$shadow_stage"; fi
        if [[ -n "$shadow_backup" && ! -e "$shadow_launcher" && ! -L "$shadow_launcher" ]]; then mv -T -- "$shadow_backup" "$shadow_launcher"; fi
    }
    trap cleanup_root EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    root_stage="$(mktemp -d /tmp/zeus-installer.XXXXXXXX)"
    chmod 755 "$root_stage"
    # Copy only this installer and the recognized release payload names. Never
    # expose a root-private directory or execute its contents as root.
    [[ -f "${BASH_SOURCE[0]}" ]] || fail 'Save install-linux.sh to a file, then run it with bash.'
    install -m 644 -- "${BASH_SOURCE[0]}" "$root_stage/install-linux.sh"
    user_args=()
    if [[ -n "$assets" ]]; then
        [[ -d "$assets" ]] || fail 'The downloaded release directory does not exist.'
        mkdir -- "$root_stage/assets"
        for filename in "$PACKAGE_FILE" "$NODE_FILE" zeus-source-linux.tar.gz uv-x86_64-unknown-linux-gnu.tar.gz; do
            if [[ -f "$assets/$filename" && ! -L "$assets/$filename" ]]; then
                install -m 644 -- "$assets/$filename" "$root_stage/assets/$filename"
            fi
        done
        user_args+=(--assets "$root_stage/assets")
    fi
    ((modify_path)) || user_args+=(--no-modify-path)
    printf 'Preparing ZeusAgent for %s. Downloaded programs run only as this user.\n' "$install_user"
    /usr/sbin/runuser -u "$install_user" -- /usr/bin/env -i HOME="$target_home" USER="$install_user" LOGNAME="$install_user" PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 TERM="${TERM:-dumb}" \
        /bin/bash --noprofile --norc -c 'cd -- "$HOME" && exec /bin/bash "$@"' zeus-install "$root_stage/install-linux.sh" "${user_args[@]}"
    dispatcher_stage="$(mktemp /usr/local/bin/.zeus-dispatch.XXXXXXXX)"
    {
        printf '%s\n' '#!/bin/bash' '# ZeusAgent managed user dispatcher' 'set -euo pipefail'
        printf 'target_user=%q\ntarget_home=%q\ntarget_uid=%q\n' "$install_user" "$target_home" "$target_uid"
        cat <<'DISPATCH'
if ((EUID == 0)); then
    export PATH=/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
    [[ "$(id -u "$target_user")" == "$target_uid" ]] || { printf '%s\n' 'Zeus: The installed user changed. Run install-linux.sh again.' >&2; exit 2; }
    exec /usr/sbin/runuser -u "$target_user" -- /usr/bin/env -i HOME="$target_home" USER="$target_user" LOGNAME="$target_user" PATH="$target_home/.local/bin:/usr/local/bin:/usr/bin:/bin" LANG=C.UTF-8 TERM="${TERM:-dumb}" \
        /bin/bash --noprofile --norc -c '
            caller_directory=$1; shift
            if ! cd -- "$caller_directory" 2>/dev/null; then
                printf "Zeus: %s cannot access %s; using %s.\n" "$USER" "$caller_directory" "$HOME" >&2
                cd -- "$HOME" || exit 2
            fi
            exec /bin/bash "$HOME/.local/bin/zeus" "$@"
        ' zeus "$(pwd -P)" "$@"
fi
[[ "$EUID" == "$target_uid" ]] || { printf '%s\n' 'Zeus: Run install-linux.sh in your own account to create a private installation.' >&2; exit 2; }
exec /bin/bash "$target_home/.local/bin/zeus" "$@"
DISPATCH
    } > "$dispatcher_stage"
    chmod 755 "$dispatcher_stage"
    [[ "$(global_identity)" == "$initial_global" ]] || fail 'The system zeus command changed during setup; it was preserved. Run the installer again after reviewing it.'
    if [[ -n "$shadow_launcher" ]]; then
        [[ -L "$shadow_launcher" && "$(readlink -- "$shadow_launcher")" == "$shadow_identity" ]] || fail 'The root npm command changed during setup; it was preserved. Run the installer again after reviewing it.'
    fi
    if ((preserve_npm)); then
        npm_backup="$(mktemp /usr/local/bin/.zeus-npm-backup.XXXXXXXX)"
        mv -T -- "$global_launcher" "$npm_backup"
        printf 'Preserved the previous npm command at %s.\n' "$npm_backup"
    fi
    mv -T -- "$dispatcher_stage" "$global_launcher"
    dispatcher_stage=''
    if [[ -n "$shadow_launcher" ]]; then
        shadow_stage="$(mktemp "$shadow_parent/.zeus-link.XXXXXXXX")"
        rm -f -- "$shadow_stage"
        ln -s -- "$global_launcher" "$shadow_stage"
        shadow_backup="$(mktemp "$shadow_parent/.zeus-npm-backup.XXXXXXXX")"
        mv -T -- "$shadow_launcher" "$shadow_backup"
        mv -T -- "$shadow_stage" "$shadow_launcher"
        shadow_stage=''
        printf 'Preserved the root npm command at %s and connected its original path to Zeus.\n' "$shadow_backup"
    fi
    printf '\nZeusAgent %s is ready. Run: zeus setup\nThen run: zeus\n' "$VERSION"
    printf 'Zeus runs as %s, including when launched from root. Settings stay in %s.\n' "$install_user" "$target_home"
    exit 0
fi
[[ -z "$install_user" || "$install_user" == "$(id -un)" ]] || fail 'Only root can select a different installation user.'
[[ -n "${HOME:-}" && "$HOME" == /* && "$HOME" != *$'\n'* ]] || fail 'HOME must be an absolute directory.'
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
[[ "$data_home" == /* && "$data_home" != *$'\n'* ]] || fail 'XDG_DATA_HOME must be an absolute directory.'
if [[ -n "$assets" ]]; then
    [[ -d "$assets" ]] || fail 'The downloaded release directory does not exist.'
    assets="$(cd -- "$assets" && pwd -P)"
fi

install_dependencies

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
