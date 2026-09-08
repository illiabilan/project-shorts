#!/usr/bin/env bash
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"
exec "$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/automation/poster.py" --auth "$@"
