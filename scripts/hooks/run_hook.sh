#!/usr/bin/env bash
# Run a Python hook with whichever interpreter exists. `exec` keeps the hook's
# exit code (2 = block) without falling through to another interpreter.
script="$1"
if command -v py >/dev/null 2>&1; then exec py -3 "$script"; fi
if command -v python3 >/dev/null 2>&1; then exec python3 "$script"; fi
exec python "$script"
