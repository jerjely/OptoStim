#!/bin/bash
# OptoStim - install from source (macOS). Double-click this file.
# Most people should use the .pkg installer from the Releases page instead.
cd "$(dirname "$0")" || exit 1

fail() {
  echo
  echo "Something went wrong: $1"
  echo "Press Return to close this window."
  read -r _
  exit 1
}

echo "OptoStim - install from source (macOS)"
echo

# ---- conda (PATH or the usual install folders)?
CONDA=""
for c in conda "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "$HOME/miniforge3/bin/conda" \
         "$HOME/mambaforge/bin/conda" /opt/homebrew/Caskroom/miniconda/base/bin/conda \
         /usr/local/Caskroom/miniconda/base/bin/conda; do
  if command -v "$c" >/dev/null 2>&1; then
    CONDA="$(command -v "$c")"
    break
  fi
done

if [ -n "$CONDA" ]; then
  echo "Found conda: $CONDA"
  echo "Creating a conda environment in the folder .conda_env (Python 3.12, conda-forge)..."
  "$CONDA" create -y -p "$PWD/.conda_env" -c conda-forge --override-channels python=3.12 pip \
    || fail "could not create the conda environment"
  PY="$PWD/.conda_env/bin/python"
else
  BASE=""
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 \
       && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      BASE="$(command -v "$c")"
      break
    fi
  done
  [ -n "$BASE" ] || fail "no conda and no Python 3.10 or newer found. Install Python from https://www.python.org/downloads/ and run this again."
  echo "conda not found - using a Python virtual environment in the folder .venv ($BASE)"
  "$BASE" -m venv "$PWD/.venv" || fail "could not create the virtual environment"
  PY="$PWD/.venv/bin/python"
fi

echo
echo "Installing the packages OptoStim needs..."
"$PY" -m pip install --upgrade pip || fail "pip upgrade failed"
"$PY" -m pip install -r requirements.txt || fail "package installation failed"
"$PY" -m optostim --version || fail "OptoStim did not start"

chmod +x start_optostim.command 2>/dev/null
echo
echo "Done. Start OptoStim by double-clicking start_optostim.command."
echo "Press Return to close this window."
read -r _
