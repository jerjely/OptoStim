#!/bin/bash
# Starts OptoStim from source (after install_mac.command has been run).
cd "$(dirname "$0")" || exit 1
if [ -x ".conda_env/bin/python" ]; then
  PY=".conda_env/bin/python"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "OptoStim is not installed yet. Run install_mac.command first."
  echo "Press Return to close this window."
  read -r _
  exit 1
fi
exec "$PY" -m optostim
