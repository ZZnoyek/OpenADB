#!/usr/bin/env bash
# POSIX-compatible: works when run as `bash install.sh`, `sh install.sh`,
# or `./install.sh`.
set -eu

# OpenADB installer - fetches the OpenADB binary straight from
# raw.githubusercontent.com and installs it so you can run `openadb`
# from the terminal. No GitHub releases needed.
#
# SET THESE (or override via env vars) before running:
REPO_URL="${REPO_URL:-https://github.com/USERNAME/OpenADB}"
ASSET_NAME="${ASSET_NAME:-OpenADB}"
BRANCH="${BRANCH:-main}"

CMD_NAME="openadb"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
TMP_FILE=""

if [ "$(id -u)" = "0" ]; then
    echo "warning: running as root (sudo). OpenADB installs per-user to" >&2
    echo "  $INSTALL_DIR - with sudo that's root's home, not yours." >&2
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
}

uninstall() {
    local target="$INSTALL_DIR/$CMD_NAME"
    local pathtline="export PATH=\"$INSTALL_DIR:\$PATH\""
    echo ">> uninstalling OpenADB"

    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        [ -f "$rc" ] || continue
        if grep -qF "$pathtline" "$rc"; then
            grep -vF "$pathtline" "$rc" > "$rc.tmp" \
                && mv "$rc.tmp" "$rc"
            echo "removed PATH line from $rc"
        fi
    done

    if [ -f "$target" ]; then
        rm -f "$target"
        echo "removed $target"
    else
        echo "note: $target not found (already removed)"
    fi

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
    esac
done
[ "${ARG_UNINSTALL:-0}" = "1" ] && uninstall

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

[ -n "${REPO_URL##*github.com*}" ] && die "REPO_URL must point at a GitHub repo"
repo_slug="${REPO_URL#*github.com/}"
repo_slug="${repo_slug%/}"

echo ">> fetching OpenADB from raw.githubusercontent.com"

TMP_FILE="$(mktemp)"
url="https://raw.githubusercontent.com/${repo_slug}/${BRANCH}/${ASSET_NAME}"
echo ">> downloading $url"
download "$url" "$TMP_FILE" || die "download failed from $url (check REPO_URL/BRANCH/ASSET_NAME and that the binary is committed to the repo)"

[ -s "$TMP_FILE" ] || die "downloaded file is empty - is $ASSET_NAME committed to the repo?"
chmod +x "$TMP_FILE"

mkdir -p "$INSTALL_DIR"
install -m 755 "$TMP_FILE" "$INSTALL_DIR/$CMD_NAME"
rm -f "$TMP_FILE"
TMP_FILE=""

if ! command -v "$CMD_NAME" >/dev/null 2>&1; then
    case ":$PATH:" in
        *":$INSTALL_DIR:"*) ;;
        *)
            if [ -f "$HOME/.bashrc" ]; then
                echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$HOME/.bashrc"
                echo ">> added $INSTALL_DIR to PATH in ~/.bashrc (restart your terminal)"
            elif [ -f "$HOME/.zshrc" ]; then
                echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$HOME/.zshrc"
                echo ">> added $INSTALL_DIR to PATH in ~/.zshrc (restart your terminal)"
            else
                echo ">> install to: $INSTALL_DIR/$CMD_NAME (add $INSTALL_DIR to your PATH)"
            fi
            ;;
    esac
fi

echo ">> installed $CMD_NAME to $INSTALL_DIR/$CMD_NAME"
if "$INSTALL_DIR/$CMD_NAME" -help >/dev/null 2>&1; then
    echo ">> smoke test OK - run 'openadb -help' to see usage"
else
    echo ">> installed, but smoke test failed (binary may not be the right build)"
    exit 1
fi
