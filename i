#!/usr/bin/env sh
set -eu

BASE_URL="${NEUROGATE_SETUP_BASE_URL:-https://github.com/OlegGorsky/VS-Code-NeuroGate-Extensions/raw/main}"
TMP_DIR="${TMPDIR:-/tmp}/ng-vscode-$$"
SETUP="$TMP_DIR/setup_neurogate_vscode.py"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$TMP_DIR"

download() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" "$1"
  else
    echo "curl or wget is required to download the installer." >&2
    exit 1
  fi
}

is_nixos() {
  [ -f /etc/os-release ] && grep -Eq '^ID="?nixos"?$' /etc/os-release
}

as_root() {
  if [ "$(id -u)" = "0" ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "sudo is required to install dependencies." >&2
    return 1
  fi
}

install_python3() {
  command -v python3 >/dev/null 2>&1 && return 0

  if is_nixos; then
    return 0
  fi

  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install python
      else
        echo "Homebrew is required to install Python automatically on macOS." >&2
        return 1
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update
        as_root apt-get install -y python3 curl ca-certificates
      elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y python3 curl ca-certificates
      elif command -v yum >/dev/null 2>&1; then
        as_root yum install -y python3 curl ca-certificates
      elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install python3 curl ca-certificates
      elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -Sy --needed --noconfirm python curl ca-certificates
      elif command -v apk >/dev/null 2>&1; then
        as_root apk add python3 curl ca-certificates
      else
        echo "Unsupported Linux package manager. Install python3 and run again." >&2
        return 1
      fi
      ;;
    *)
      echo "Unsupported system. Install python3 and run setup_neurogate_vscode.py manually." >&2
      return 1
      ;;
  esac
}

quote_arg() {
  printf "'%s'" "$(printf "%s" "$1" | sed "s/'/'\\\\''/g")"
}

run_setup() {
  if command -v python3 >/dev/null 2>&1; then
    python3 "$SETUP" --install-missing-deps "$@"
    return
  fi

  if is_nixos && command -v nix-shell >/dev/null 2>&1; then
    quoted_args=""
    for arg in "$@"; do
      quoted_args="$quoted_args $(quote_arg "$arg")"
    done
    nix-shell -p python3 --run "python3 $(quote_arg "$SETUP") --install-missing-deps$quoted_args"
    return
  fi

  echo "python3 was not found and could not be installed automatically." >&2
  exit 1
}

download "$BASE_URL/setup_neurogate_vscode.py" "$SETUP"
install_python3 || true
run_setup "$@"
