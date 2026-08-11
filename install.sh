#!/usr/bin/env bash
# POSIX-compatible: works when run as `bash install.sh`, `sh install.sh`,
# or `./install.sh`.
set -eu

# OpenADB installer - fetches the OpenADB binary from a GitHub RELEASE
# and installs it so you can run `openadb` from the terminal.
#
# OVERRIDE VIA ENV VARS / FLAGS (everything is optional - interactive
# prompts fill the gaps, and prompts are skipped when not on a TTY):
#   REPO_URL       GitHub repo, default https://github.com/ZZnoyek/OpenABD
#   ASSET_NAME     release asset / raw filename, default "OpenADB"
#   BRANCH         branch for bleeding-edge installs, default "main"
#   VERSION        latest | <release tag> | raw    (default: interactive menu of releases)
#   INSTALL_MODE   both | normal | opencode        (default: ask)
#   --yes          accept all defaults (no prompts)
#   --version X    same as VERSION
#   --mode X       same as INSTALL_MODE
#   --no-deps      skip the dependency install step
#   --uninstall    remove OpenADB (binary, PATH lines, symlink)
REPO_URL="${REPO_URL:-https://github.com/ZZnoyek/OpenABD}"
ASSET_NAME="${ASSET_NAME:-OpenADB}"
BRANCH="${BRANCH:-main}"
VERSION="${VERSION:-}"
INSTALL_MODE="${INSTALL_MODE:-}"

[ -n "${REPO_URL##*github.com*}" ] && die "REPO_URL must point at a GitHub repo"
repo_slug="${REPO_URL#*github.com/}"
repo_slug="${repo_slug%/}"

CMD_NAME="openadb"
NORMAL_DIR="$HOME/.local/bin"
OPCODE_DIR="$HOME/.opencode/bin"
TMP_FILE=""
ARG_YES=0

if [ "$(id -u)" = "0" ]; then
    echo "warning: running as root (sudo). OpenADB installs per-user to" >&2
    echo "  your home directory - with sudo that's root's home, not yours." >&2
    echo "  Run WITHOUT sudo; the script will ask for sudo itself when" >&2
    echo "  installing system dependencies." >&2
fi

cleanup() {
    if [ -n "$TMP_FILE" ]; then
        rm -f "$TMP_FILE"
    fi
}
trap cleanup EXIT

die() {
    echo "error: $*" >&2
    exit 1
}

is_tty() {
    [ -t 0 ]
}

download() {
    local url="$1"
    local out="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "$out" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$out" "$url"
    else
        die "neither curl nor wget is installed - install one of them first"
    fi
}

remove_deps() {
    # Removes the same packages install_deps would have added, per distro.
    case "$(command -v apt-get || echo)" in
        /*) sudo apt-get remove -y adb tesseract-ocr xdg-utils \
                || echo "note: apt remove returned an error" ;;
    esac
    case "$(command -v dnf || echo)" in
        /*) sudo dnf remove -y android-tools tesseract xdg-utils \
                || echo "note: dnf remove returned an error" ;;
    esac
    case "$(command -v pacman || echo)" in
        /*) sudo pacman -Rs --noconfirm android-tools tesseract xdg-utils \
                || echo "note: pacman remove returned an error" ;;
    esac
    case "$(command -v zypper || echo)" in
        /*) sudo zypper remove -y android-tools tesseract xdg-utils \
                || echo "note: zypper remove returned an error" ;;
    esac
    case "$(command -v yum || echo)" in
        /*) sudo yum remove -y android-tools tesseract xdg-utils \
                || echo "note: yum remove returned an error" ;;
    esac
    case "$(command -v apk || echo)" in
        /*) sudo apk del android-tools tesseract-ocr xdg-utils \
                || echo "note: apk del returned an error" ;;
    esac
}

# Remove a PATH line from every rc file that contains it.
remove_pathtlines() {
    local pathtline
    for pathtline in \
        "export PATH=\"$NORMAL_DIR:\$PATH\"" \
        "export PATH=\"$OPCODE_DIR:\$PATH\""; do
        for rc in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" \
                  "$HOME/.profile"; do
            [ -f "$rc" ] || continue
            if grep -qF "$pathtline" "$rc"; then
                grep -vF "$pathtline" "$rc" > "$rc.tmp" || :
                mv "$rc.tmp" "$rc"
                echo "removed PATH line from $rc"
            fi
        done
    done
}

uninstall() {
    echo ">> uninstalling OpenADB"

    remove_pathtlines

    for target in "$NORMAL_DIR/$CMD_NAME" "$OPCODE_DIR/$CMD_NAME"; do
        if [ -L "$target" ]; then
            rm -f "$target"
            echo "removed symlink $target"
        elif [ -f "$target" ]; then
            rm -f "$target"
            echo "removed $target"
        fi
    done

    if [ "${SKIP_DEPS:-0}" != "1" ]; then
        echo "OpenADB may have installed these dependencies: adb, tesseract, xdg-utils."
        printf "Remove them too? [y/N] "
        read -r ans || ans=""
        case "$ans" in
            [yY] | [yY][eE][sS])
                echo ">> removing dependencies (may ask for sudo)..."
                remove_deps
                echo "dependencies removed"
                ;;
        esac
    fi
    echo "uninstall complete"
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --uninstall) ARG_UNINSTALL=1 ;;
        --no-deps) SKIP_DEPS=1 ;;
        --yes) ARG_YES=1 ;;
        --version) NEED_VERSION=1 ;;
        --mode) NEED_MODE=1 ;;
        --version=*) VERSION="${arg#--version=}" ;;
        --mode=*) INSTALL_MODE="${arg#--mode=}" ;;
    esac
done
[ "${ARG_UNINSTALL:-0}" = "1" ] && uninstall

# Two-value flags: --version X --mode Y (also accept -v / -m short forms).
prev=""
for arg in "$@"; do
    if [ "$prev" = "1" ]; then VERSION="$arg"; prev=""; continue; fi
    if [ "$prev" = "2" ]; then INSTALL_MODE="$arg"; prev=""; continue; fi
    case "$arg" in
        --version|-v) prev=1 ;;
        --mode|-m) prev=2 ;;
    esac
done

# ---- interactive prompts (skipped unless on a TTY and --yes not given) ----

# Fetch the tag name of every GitHub release that ships a matching asset,
# newest first (the API returns releases newest-first). Prints nothing if
# there are no releases yet or none has a matching asset.
list_release_tags() {
    local body
    body="$(curl -fsSL --retry 3 \
        "https://api.github.com/repos/${repo_slug}/releases?per_page=30" \
        2>/dev/null)" || return 1
    if command -v jq >/dev/null 2>&1; then
        jq -r --arg a "$ASSET_NAME" '
            [ .[]
              | select(any(.assets[];
                  (.name | ascii_downcase) == ($a | ascii_downcase)
                  or ((.name | ascii_downcase)
                      | startswith(($a | ascii_downcase) + "_"))))
              | .tag_name ] | .[]' <<<"$body" 2>/dev/null
        return 0
    fi
    # No jq: list every tag (a tag with no matching asset fails cleanly later).
    printf '%s\n' "$body" \
        | grep -o '"tag_name": *"[^"]*"' \
        | sed 's/.*: *"\(.*\)"/\1/'
}

ask_version() {
    local tags line ans i n=2
    echo ">> looking up OpenADB releases..."
    tags="$(list_release_tags 2>/dev/null || true)"
    echo "Which version of OpenADB do you want to install?"
    echo "  1) latest release          (recommended)"
    if [ -z "$tags" ]; then
        echo "     (no releases found - will fall back to the $BRANCH branch)"
    else
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            printf '  %s) %s\n' "$n" "$line"
            n=$((n+1))
        done <<EOF
$tags
EOF
    fi
    echo "  0) cancel"
    printf 'Choose [1-%s, default 1]: ' "$((n-1))"
    read -r ans || ans=""
    case "$ans" in
        "" | 1) VERSION="latest" ;;
        0) die "install cancelled" ;;
        *[!0-9]*)
            # not a number - treat it as a release tag typed directly
            VERSION="$ans" ;;
        *)
            i=1
            while IFS= read -r line; do
                [ -n "$line" ] || continue
                i=$((i+1))
                [ "$i" -eq "$ans" ] && { VERSION="$line"; break; }
            done <<EOF
$tags
EOF
            [ -n "$VERSION" ] || die "invalid choice: $ans"
            ;;
    esac
}

ask_mode() {
    echo "Where should the '$CMD_NAME' command be installed?"
    echo "  1) both places            (recommended)"
    echo "       normal PATH (~/.local/bin) + opencode's path (~/.opencode/bin)"
    echo "  2) normal PATH only       (terminal users)"
    echo "  3) opencode path only     (AI assistant shells, no terminal use)"
    printf "Choose [1-3, default 1]: "
    read -r ans || ans="1"
    case "$ans" in
        2) INSTALL_MODE="normal" ;;
        3) INSTALL_MODE="opencode" ;;
        *) INSTALL_MODE="both" ;;
    esac
}

[ -z "$VERSION" ] && {
    if [ "$ARG_YES" = "1" ] || ! is_tty; then
        VERSION="latest"
    else
        ask_version
    fi
}
[ -z "$INSTALL_MODE" ] && {
    if [ "$ARG_YES" = "1" ] || ! is_tty; then
        INSTALL_MODE="both"
    else
        ask_mode
    fi
}

# ---- dependencies ----

deps_ok() {
    for b in adb tesseract xdg-open; do
        command -v "$b" >/dev/null 2>&1 || return 1
    done
    return 0
}

install_deps() {
    # Maps adb/tesseract/xdg-open to the right package per distro.
    local missing=""
    case "$(command -v apt-get || echo)" in
        /*) for p in adb tesseract-ocr xdg-utils; do
                dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"
            done
            [ -z "$missing" ] && return 0
            sudo apt-get update && sudo apt-get install -y $missing ;;
        *) : ;;
    esac
    case "$(command -v dnf || echo)" in
        /*) missing=""
            for b in adb tesseract xdg-open; do
                command -v "$b" >/dev/null 2>&1 || missing="$missing $b"
            done
            [ -z "$missing" ] && return 0
            missing=" $(echo $missing | sed 's/ adb/ android-tools/')"
            sudo dnf install -y $missing ;;
        *) : ;;
    esac
    case "$(command -v pacman || echo)" in
        /*) missing=""
            for b in adb tesseract xdg-open; do
                command -v "$b" >/dev/null 2>&1 || missing="$missing $b"
            done
            [ -z "$missing" ] && return 0
            missing=" $(echo $missing | sed 's/ adb/ android-tools/')"
            sudo pacman -S --noconfirm $missing ;;
        *) : ;;
    esac
    case "$(command -v zypper || echo)" in
        /*) missing=""
            for b in adb tesseract xdg-open; do
                command -v "$b" >/dev/null 2>&1 || missing="$missing $b"
            done
            [ -z "$missing" ] && return 0
            missing=" $(echo $missing | sed 's/ adb/ android-tools/')"
            sudo zypper install -y $missing ;;
        *) : ;;
    esac
    case "$(command -v yum || echo)" in
        /*) missing=""
            for b in adb tesseract xdg-open; do
                command -v "$b" >/dev/null 2>&1 || missing="$missing $b"
            done
            [ -z "$missing" ] && return 0
            missing=" $(echo $missing | sed 's/ adb/ android-tools/')"
            sudo yum install -y $missing ;;
        *) : ;;
    esac
    case "$(command -v apk || echo)" in
        /*) missing=""
            for b in adb tesseract xdg-open; do
                command -v "$b" >/dev/null 2>&1 || missing="$missing $b"
            done
            [ -z "$missing" ] && return 0
            missing=" $(echo $missing | sed 's/ adb/ android-tools/')"
            sudo apk add $missing ;;
        *) : ;;
    esac
    return 1
}

if [ "${SKIP_DEPS:-0}" != "1" ]; then
    echo ">> checking dependencies (adb, tesseract, xdg-open)"
    if deps_ok; then
        echo ">> dependencies already installed"
    else
        echo ">> installing dependencies (may ask for sudo):"
        install_deps || true
        if deps_ok; then
            echo ">> dependencies installed"
        else
            echo "warning: could not install all dependencies. OpenADB needs adb"
            echo "to work at all, and tesseract for OCR - install them manually."
        fi
    fi
else
    echo ">> skipping dependency check (--no-deps)"
fi

# ---- resolve the download source ----

# Fetch the browser_download_url of the release binary. The asset is named
# OpenADB_R1, OpenADB_R2, ... so we match by NAME_PREFIX (ASSET_NAME, default
# "OpenADB") and prefer the highest version number if several exist. Prints
# the URL on success, prints nothing (and returns 1) if there's no release /
# no matching asset.
release_asset_url() {
    local url="$1"
    local body
    body="$(curl -fsSL --retry 3 "$url" 2>/dev/null)" || return 1
    if command -v jq >/dev/null 2>&1; then
        # ASSET_NAME by itself, or ASSET_NAME_<digits>... pick highest number.
        jq -r --arg a "$ASSET_NAME" '
            def num: (capture("^[_a-z]*[^0-9]*(?<n>[0-9]+)[^0-9.]*$")?
                     | .n | tonumber) // 0;
            [ .assets[]
              | select((.name | ascii_downcase) == ($a | ascii_downcase)
                       or ((.name | ascii_downcase)
                           | startswith(($a | ascii_downcase) + "_"))) ]
            | sort_by(.name | num)
            | last
            | .browser_download_url' <<<"$body" 2>/dev/null | head -n1
        return 0
    fi
    # No jq: pull every browser_download_url, keep the ones whose filename
    # starts with ASSET_NAME_, and pick the one with the highest number.
    printf '%s\n' "$body" \
        | grep -o '"browser_download_url": *"[^"]*"' \
        | sed 's/^[^"]*"[^"]*" *: *"\(.*\)"$/\1/' \
        | while read -r u; do
            n="${u##*/}"
            nl="$(printf '%s' "$n" | tr '[:upper:]' '[:lower:]')"
            al="$(printf '%s' "$ASSET_NAME" | tr '[:upper:]' '[:lower:]')"
            if [ "$nl" = "$al" ] || [ "${nl#"$al"_}" != "$nl" ]; then
                num="$(printf '%s' "$n" \
                       | sed 's/.*[^0-9]\([0-9][0-9]*\)[^0-9.]*$/\1/')"
                case "$num" in
                    *[!0-9]*) num=0 ;;
                esac
                printf '%s\t%s\n' "$num" "$u"
            fi
        done | sort -t"$(printf '\t')" -k1,1n | tail -n1 | cut -f2
}

case "$VERSION" in
    raw)
        fetch_url="https://raw.githubusercontent.com/${repo_slug}/${BRANCH}/${ASSET_NAME}"
        echo ">> fetching $ASSET_NAME (bleeding-edge) from raw.githubusercontent.com"
        ;;
    latest)
        fetch_url="$(release_asset_url \
            "https://api.github.com/repos/${repo_slug}/releases/latest")" || true
        if [ -z "$fetch_url" ]; then
            echo "note: no GitHub release found yet - falling back to the ${BRANCH} branch"
            fetch_url="https://raw.githubusercontent.com/${repo_slug}/${BRANCH}/${ASSET_NAME}"
        else
            echo ">> fetching $ASSET_NAME from the latest GitHub release"
        fi
        ;;
    *)
        fetch_url="$(release_asset_url \
            "https://api.github.com/repos/${repo_slug}/releases/tags/${VERSION}")" || true
        [ -n "$fetch_url" ] \
            || die "no release tag '$VERSION' found (or it has no asset named '$ASSET_NAME')"
        echo ">> fetching $ASSET_NAME from release tag ${VERSION}"
        ;;
esac

TMP_FILE="$(mktemp)"
echo ">> downloading $fetch_url"
download "$fetch_url" "$TMP_FILE" || die "download failed from $fetch_url"

[ -s "$TMP_FILE" ] || die "downloaded file is empty - check the release/asset name"
chmod +x "$TMP_FILE"

# ---- install into the chosen location(s) ----

install_binary() {
    local dir="$1"
    mkdir -p "$dir"
    install -m 755 "$TMP_FILE" "$dir/$CMD_NAME"
    echo ">> installed $CMD_NAME to $dir/$CMD_NAME"
}

# Add $NORMAL_DIR to PATH in every shell rc file that exists, deduped per
# file so re-running the installer never appends the line twice.
add_pathtline() {
    local dir="$1"
    local pathtline="export PATH=\"$dir:\$PATH\""
    local updated=0 found_rc=0 rc
    for rc in "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" \
              "$HOME/.profile"; do
        [ -f "$rc" ] || continue
        found_rc=1
        if ! grep -qF "$pathtline" "$rc"; then
            echo "$pathtline" >> "$rc"
            echo ">> added $dir to PATH in $rc"
            updated=1
        fi
    done
    if [ "$found_rc" = "0" ]; then
        rc="$HOME/.bashrc"
        echo "$pathtline" >> "$rc"
        echo ">> created $rc and added $dir to PATH"
        updated=1
    fi
    if [ "$updated" = "1" ]; then
        echo ">> PATH updated - restart your terminal (or run: source ~/.bashrc)"
    elif [ "$found_rc" = "1" ]; then
        echo ">> PATH already configured in shell rc files"
    fi
}

# Symlink $CMD_NAME into opencode's bin dir so non-interactive opencode
# shells (bash -c, PATH straight from the opencode process) see it too.
link_into_opencode() {
    local target="$1"
    mkdir -p "$OPCODE_DIR" 2>/dev/null || return 0
    [ -d "$OPCODE_DIR" ] || return 0
    if [ -e "$OPCODE_DIR/$CMD_NAME" ]; then
        if [ -L "$OPCODE_DIR/$CMD_NAME" ] \
           && [ "$(readlink -f "$OPCODE_DIR/$CMD_NAME")" = "$(readlink -f "$target")" ]; then
            : # already linked to this install - nothing to do
        else
            echo "note: $OPCODE_DIR/$CMD_NAME already exists and is not this install - leaving it" >&2
        fi
        return 0
    fi
    if ln -s "$target" "$OPCODE_DIR/$CMD_NAME" 2>/dev/null; then
        echo ">> linked $CMD_NAME into opencode's path ($OPCODE_DIR)"
    fi
}

case "$INSTALL_MODE" in
    normal)
        install_binary "$NORMAL_DIR"
        if ! command -v "$CMD_NAME" >/dev/null 2>&1; then
            case ":$PATH:" in
                *":$NORMAL_DIR:"*) : ;;
                *) add_pathtline "$NORMAL_DIR" ;;
            esac
        fi
        ;;
    opencode)
        install_binary "$OPCODE_DIR"
        ;;
    both)
        install_binary "$NORMAL_DIR"
        if ! command -v "$CMD_NAME" >/dev/null 2>&1; then
            case ":$PATH:" in
                *":$NORMAL_DIR:"*) : ;;
                *) add_pathtline "$NORMAL_DIR" ;;
            esac
        fi
        link_into_opencode "$NORMAL_DIR/$CMD_NAME"
        ;;
    *)
        die "unknown INSTALL_MODE '$INSTALL_MODE' (use both | normal | opencode)"
        ;;
esac

rm -f "$TMP_FILE"
TMP_FILE=""

echo ">> installed $CMD_NAME (mode: $INSTALL_MODE, source: $VERSION)"
if "$NORMAL_DIR/$CMD_NAME" -help >/dev/null 2>&1 \
   || "$OPCODE_DIR/$CMD_NAME" -help >/dev/null 2>&1; then
    echo ">> smoke test OK - run 'openadb -help' to see usage"
else
    echo ">> installed, but smoke test failed (binary may not be the right build)"
    exit 1
fi
