#!/usr/bin/env bash
# End-to-end dry run with offline mock providers in a throwaway workspace.
# Produces a real synchronized MP4 without any API keys or spend.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WS="${1:-$(mktemp -d)}"
mkdir -p "$WS"
cp -r "$REPO/config" "$REPO/assets" "$WS/"
export KIDSVIDEO_HOME="$WS"
kv() { kidsvideo --mock "$@"; }

kv new demo-song --title "Trái Cây Gì Đây?" --topic fruit --duration 30
kv build demo-song --auto-approve --preset preview
kv thumbnail demo-song
kv thumbnail demo-song --pick 1
kv metadata demo-song > /dev/null
kv status demo-song
echo
echo "Workspace: $WS"
echo "Video:     $WS/projects/demo-song/output/demo-song-preview.mp4"
