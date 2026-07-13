#!/bin/sh
set -eu

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET_DIR=/home/bazzite/homebrew/plugins/DiscShelf

install -d -m 755 "$TARGET_DIR/dist"
install -m 644 "$SOURCE_DIR/dist/index.js" "$TARGET_DIR/dist/index.js"
install -m 644 "$SOURCE_DIR/main.py" "$TARGET_DIR/main.py"
install -m 644 "$SOURCE_DIR/plugin.json" "$TARGET_DIR/plugin.json"
install -m 644 "$SOURCE_DIR/package.json" "$TARGET_DIR/package.json"

systemctl restart plugin_loader.service
