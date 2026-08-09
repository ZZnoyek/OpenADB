#!/usr/bin/env bash
set -euo pipefail

# OpenADB installer - fetches the OpenADB binary from a GitHub release and
# installs it so you can run `openadb` from the terminal.
#
# SET THESE (or override via env vars) BEFORE publishing your release:
REPO_URL="${REPO_URL:-https://github.com/USERNAME/OpenADB}"
ASSET_NAME="${ASSET_NAME:-OpenADB}"

CMD_NAME="openadb"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
TMP_FILE=""

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
    echo ">> uninstalling OpenADB"

    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        [ -f "$rc" ] || continue
        if grep -qF 'export PATH="$HOME/.local/bin:$PATH"' "$rc"; then
            grep -vF 'export PATH="$HOME/.local/bin:$PATH"' "$rc" > "$rc.tmp" \
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
        read -r -p "Remove them too? [y/N] " ans || ans=""
        case "${ans,,}" in
            y | yes)
                echo ">> removing dependencies (may ask for sudo)..."
                remove_deps
                echo "dependencies removed"
                ;;
        esac
    fi
    echo "uninstall complete"
    exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall
[ "${1:-}" = "--no-deps" ] && SKIP_DEPS=1

deps_ok() {
    for b in adb tesseract xdg-open; do
        command -v "$b" >/dev/null 2>&1 || return 1
    done
    return 0
}

install_deps() {
    # Maps adb/tesseract/xdg-open to the right package per distro.
    local pkgs=()
    case "$(command -v apt-get || echo)" in
        /*) for p in adb tesseract-ocr xdg-utils; do
                dpkg -s "$p" >/dev/null 2>&1 || pkgs+=("$p")
            done
            [ ${#pkgs[@]} -eq 0 ] && return 0
            sudo apt-get update && sudo apt-get install -y "${pkgs[@]}" ;;
        *) : ;;
    esac
    case "$(command -v dnf || echo)" in
        /*) pkgs=()
            for b in adb tesseract xdg-open; do
                command -v "$b" >/dev/null 2>&1 || pkgs+=("$b")
            done
            [ ${#pkgs[@]} -eq 0 ] && return 0
            pkgs2=()
            for p in "${pkgs[@]}"; do
                [ "$p" = "adb" ] && p="android-tools"
                pkgs2+=("$p")
            done
            sudo dnf install -y "${pkgs2[@]}" ;;
        *) : ;;
    esac
    case "$(command -v pacman || echo)" in
        /*) pkgs=()
            for b in adb tesseract xdg-open; do
                command -v "$b" >/dev/null 2>&1 || pkgs+=("$b")
            done
            [ ${#pkgs[@]} -eq 0 ] && return 0
            pkgs2=()
            for p in "${pkgs[@]}"; do
                [ "$p" = "adb" ] && p="android-tools"
                pkgs2+=("$p")
            done
            sudo pacman -S --noconfirm "${pkgs2[@]}" ;;
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
        install_deps
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

echo ">> fetching OpenADB release from $REPO_URL"

TMP_FILE="$(mktemp)"
url=""
if command -v curl >/dev/null 2>&1; then
    url="$(curl -fsSL "https://api.github.com/repos/${repo_slug}/releases/latest" 2>/dev/null \
        | grep -o "\"browser_download_url\": *\"[^\"]*${ASSET_NAME}[^\"]*\"" \
        | sed 's/.*"browser_download_url": *"//; s/"$//' \
        | head -1 || true)"
fi
if [ -z "$url" ]; then
    echo ">> no release API match, trying standard release-asset URL"
    url="https://github.com/${repo_slug}/releases/latest/download/${ASSET_NAME}"
fi

download "$url" "$TMP_FILE" || die "download failed from $url (check REPO_URL/ASSET_NAME and that the binary is attached to a release)"

[ -s "$TMP_FILE" ] || die "downloaded file is empty - is $ASSET_NAME attached to the release?"
chmod +x "$TMP_FILE"

mkdir -p "$INSTALL_DIR"
install -m 755 "$TMP_FILE" "$INSTALL_DIR/$CMD_NAME"
rm -f "$TMP_FILE"
TMP_FILE=""

if ! command -v "$CMD_NAME" >/dev/null 2>&1; then
    case ":$PATH:" in
        *":$INSTALL_DIR:"*) ;;
        *)
            if command -v bash >/dev/null 2>&1 && [ -f "$HOME/.bashrc" ]; then
                echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$HOME/.bashrc"
                echo ">> added ~/.local/bin to PATH in ~/.bashrc (restart your terminal)"
            elif [ -f "$HOME/.zshrc" ]; then
                echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$HOME/.zshrc"
                echo ">> added ~/.local/bin to PATH in ~/.zshrc (restart your terminal)"
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
