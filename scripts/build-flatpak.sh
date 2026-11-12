#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/twinly-build.XXXXXX")
OUTPUT_DIR=${1:-"$PROJECT_DIR/dist"}
mkdir -p "$OUTPUT_DIR"
APP_ID=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["app-id"])' "$PROJECT_DIR/packaging/io.github.paullinux_gn.Twinly.json")
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak-builder --user --install-deps-from=flathub --force-clean --repo="$WORK_DIR/repo" "$WORK_DIR/build" "$PROJECT_DIR/packaging/io.github.paullinux_gn.Twinly.json"
flatpak build-bundle "$WORK_DIR/repo" "$OUTPUT_DIR/Twinly-0.4.1.flatpak" "$APP_ID" --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo
printf 'Bundle: %s/Twinly-0.4.1.flatpak\nBuild files: %s\n' "$OUTPUT_DIR" "$WORK_DIR"
