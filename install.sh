#!/bin/sh
# Install uv if needed, then install Diplomacy and open it.
set -eu
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    echo "Install curl or wget, then run ./install.sh again." >&2
    exit 1
  fi
fi

if [ -f "$HOME/.local/bin/env" ]; then
  # The uv installer writes this file. A non-interactive shell does not load it.
  # shellcheck disable=SC1091
  . "$HOME/.local/bin/env"
fi
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv was not installed. Open a new terminal and run ./install.sh again." >&2
  exit 1
fi

uv python install 3.12
uv sync
exec uv run python app.py
