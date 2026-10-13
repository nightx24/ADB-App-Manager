#!/bin/sh
export PYTHONPATH="/app/lib/python3.11/site-packages:/app/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
if [ -x /run/host/usr/bin/adb ] && ! command -v adb >/dev/null 2>&1; then
  export PATH="/run/host/usr/bin:$PATH"
fi
exec python3 /app/share/adb-app-manager/main.py "$@"
