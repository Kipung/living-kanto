#!/bin/sh
set -eu
cd "$(dirname "$0")/../server/living_kanto/mechanics"
npm ci --omit=optional --ignore-scripts
