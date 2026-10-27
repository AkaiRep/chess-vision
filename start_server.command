#!/bin/bash
# chess-vision server for macOS. Double-click in Finder or run ./start_server.command
# On first start installs Python 3.11+, Stockfish and the Python packages it needs.
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

find_python() {
    for p in python3.13 python3.12 python3.11 python3; do
        if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            echo "$p"
            return
        fi
    done
}

ensure_brew() {
    command -v brew >/dev/null 2>&1 && return
    echo "Homebrew is needed to install Python/Stockfish."
    read -r -p "Install Homebrew now? [Y/n] " answer
    if [[ "$answer" =~ ^[Nn] ]]; then
        echo "Install it from https://brew.sh and run this script again."
        exit 1
    fi
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
}

if [ ! -x .venv/bin/python ]; then
    PY="$(find_python)"
    if [ -z "$PY" ]; then
        ensure_brew
        brew install python@3.12
        PY="$(find_python)"
    fi
    echo "Creating virtual environment with $PY..."
    "$PY" -m venv .venv
fi

if ! command -v stockfish >/dev/null 2>&1; then
    ensure_brew
    brew install stockfish
fi

.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements-server.txt
exec .venv/bin/python -m server "$@"
