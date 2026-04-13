#!/usr/bin/env sh
set -eu

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

uv run ruff check .
uv run pytest -q
