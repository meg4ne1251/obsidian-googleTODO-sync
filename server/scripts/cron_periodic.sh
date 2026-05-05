#!/usr/bin/env bash
# 定期実行ラッパー：sync → mirror → sync を livesync_vault ロック下で実行する。
# cron からはこのスクリプトを呼び出すこと。
#
# 例: */5 * * * *  /opt/obsidian-sync/scripts/cron_periodic.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${GTODO_CONFIG:-$ROOT/config/config.yaml}"

cd "$ROOT"

exec python3 -m src.cron_runner --config "$CONFIG"
