#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$ROOT/.runtime"
CONDA="$RUNTIME/miniforge3"
ENV="$ROOT/.venv"
CACHE="$ROOT/.cache/pip"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This launcher is for macOS only."
  read -r -p "Press Enter to close..."
  exit 1
fi

mkdir -p "$RUNTIME" "$CACHE"
export PIP_CACHE_DIR="$CACHE"

if [[ ! -x "$CONDA/bin/conda" ]]; then
  case "$(uname -m)" in
    arm64) installer="Miniforge3-MacOSX-arm64.sh" ;;
    x86_64) installer="Miniforge3-MacOSX-x86_64.sh" ;;
    *) echo "Unsupported macOS architecture: $(uname -m)"; read -r -p "Press Enter to close..."; exit 1 ;;
  esac
  echo "[1/4] Downloading the private Python runtime..."
  curl -fL --retry 3 "https://github.com/conda-forge/miniforge/releases/latest/download/$installer" -o "$RUNTIME/miniforge.sh"
  echo "[2/4] Installing the private Python runtime..."
  bash "$RUNTIME/miniforge.sh" -b -p "$CONDA"
  rm -f "$RUNTIME/miniforge.sh"
fi

if [[ ! -x "$CONDA/bin/conda" ]]; then
  echo "Miniforge installation completed, but conda was not found in $CONDA"
  read -r -p "Press Enter to close..."
  exit 1
fi

if [[ ! -x "$ENV/bin/python" ]]; then
  echo "[3/4] Creating the local Python environment..."
  "$CONDA/bin/conda" create -p "$ENV" python=3.10 -y
fi

if [[ ! -f "$ROOT/.deps-ready-v2" ]]; then
  echo "[4/4] Installing dependencies, including PyAV and FFmpeg libraries..."
  "$ENV/bin/python" -m pip install --upgrade pip
  "$ENV/bin/python" -m pip install --upgrade --force-reinstall --only-binary=:all: 'av>=14.0,<15.0'
  "$ENV/bin/python" -m pip install -r "$ROOT/requirements.txt"
  touch "$ROOT/.deps-ready-v2"
fi

"$ENV/bin/python" -c "import av; print('PyAV/FFmpeg runtime: OK')" || { echo "PyAV could not load its FFmpeg libraries. Remove .venv and run again."; exit 1; }

mkdir -p "$ROOT/models/whisper" "$ROOT/models/argos" "$ROOT/output" "$ROOT/temp" "$ROOT/logs" "$ROOT/bin"
cd "$ROOT"
echo "Starting TranscribeIt. Models will be downloaded into this folder on first use."
exec "$ENV/bin/python" "$ROOT/main.py"
