#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <archive.tar.gz> [workdir]" >&2
  exit 1
fi

ARCHIVE="$1"
WORKDIR="${2:-$(mktemp -d)}"
mkdir -p "$WORKDIR"
OUTDIR="$WORKDIR/empty_images_contract"
mkdir -p "$OUTDIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_SCRIPT="$SCRIPT_DIR/verify_release_bundle.sh"

if [[ ! -x "$VERIFY_SCRIPT" ]]; then
  echo "Missing executable verify script: $VERIFY_SCRIPT" >&2
  exit 2
fi

VERIFY_LOG="$OUTDIR/verify_run.txt"
"$VERIFY_SCRIPT" "$ARCHIVE" "$OUTDIR" > "$VERIFY_LOG"

BIN_PATH="$(awk -F= '/^binary=/{print $2}' "$VERIFY_LOG" | tail -n 1)"
if [[ -z "$BIN_PATH" || ! -x "$BIN_PATH" ]]; then
  echo "Binary path is invalid after verify: $BIN_PATH" >&2
  exit 3
fi
printf '%s\n' "$BIN_PATH" > "$OUTDIR/binary_path.txt"

PROJECT_DIR="$OUTDIR/case/project"
IMAGES_DIR="$OUTDIR/case/images"
VOICES_DIR="$OUTDIR/case/voices"
mkdir -p "$PROJECT_DIR" "$IMAGES_DIR" "$VOICES_DIR"

cat > "$PROJECT_DIR/draft_content.json" <<'JSON'
{
  "draft_materials": [],
  "tracks": []
}
JSON

python3 - <<'PY' "$VOICES_DIR/scene_001.wav"
import struct
import sys
import wave
from pathlib import Path

out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
framerate = 16000
seconds = 1
samples = [0] * (framerate * seconds)
with wave.open(str(out), 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(framerate)
    frames = b''.join(struct.pack('<h', s) for s in samples)
    wf.writeframes(frames)
PY

set +e
"$BIN_PATH" --mode inspect --project "$PROJECT_DIR" --images "$IMAGES_DIR" --voices "$VOICES_DIR" > "$OUTDIR/empty_images_stdout.txt" 2> "$OUTDIR/empty_images_stderr.txt"
EXIT_CODE=$?
set -e
printf '%s\n' "$EXIT_CODE" > "$OUTDIR/empty_images_exit_code.txt"

if [[ "$EXIT_CODE" -eq 0 ]]; then
  echo "EMPTY_IMAGES_CONTRACT_FAIL: expected non-zero exit code" > "$OUTDIR/empty_images_check.txt"
  exit 4
fi

if ! grep -Fq "No image files found in:" "$OUTDIR/empty_images_stderr.txt"; then
  echo "EMPTY_IMAGES_CONTRACT_FAIL: missing expected error text" > "$OUTDIR/empty_images_check.txt"
  exit 5
fi

echo "EMPTY_IMAGES_CONTRACT_OK" > "$OUTDIR/empty_images_check.txt"

find "$OUTDIR" -maxdepth 3 -type f | sort > "$OUTDIR/artifact_list.txt"
sha256sum "$OUTDIR"/*.txt "$OUTDIR"/verify_output/* > "$OUTDIR/evidence_sha256.txt"

cat <<REPORT
CONTRACT_OK
archive=$(realpath "$ARCHIVE")
binary=$BIN_PATH
output_dir=$OUTDIR
REPORT
