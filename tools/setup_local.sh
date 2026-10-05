#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_PIN=037335f4c725d7c9aecdac87066f2002b4bd7e14
if [ ! -f "$PROJECT_ROOT/reference/pokefirered/src/data/pokemon/species_info.h" ]; then
  mkdir -p "$PROJECT_ROOT/reference"
  git clone https://github.com/pret/pokefirered.git "$PROJECT_ROOT/reference/pokefirered"
  git -C "$PROJECT_ROOT/reference/pokefirered" checkout --detach "$SOURCE_PIN"
fi
if [ -e "$PROJECT_ROOT/reference/pokefirered/.git" ]; then
  ACTUAL_SOURCE_PIN="$(git -C "$PROJECT_ROOT/reference/pokefirered" rev-parse HEAD)"
  if [ "$ACTUAL_SOURCE_PIN" != "$SOURCE_PIN" ]; then
  printf '%s\n' 'The existing reference checkout differs from the documented source pin.' 'Preserve any local reference edits, then check out the pinned revision before running setup.' >&2
    exit 1
  fi
fi
python3 -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/python" -m pip install -e "$PROJECT_ROOT/server[dev]" pillow
bash "$PROJECT_ROOT/tools/setup_battles.sh"
printf '%s\n' 'Ready. Start with: bash tools/run_local.sh'
