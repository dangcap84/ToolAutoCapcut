#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <archive.tar.gz> [workdir]" >&2
  exit 1
fi

ARCHIVE="$1"
WORKDIR="${2:-$(mktemp -d)}"
mkdir -p "$WORKDIR"
OUTDIR="$WORKDIR/mismatch_count_contract"
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

python3 - <<'PY' "$VOICES_DIR/scene_001.wav" "$VOICES_DIR/scene_002.wav" "$IMAGES_DIR/scene_001.png"
import struct
import sys
import wave
from pathlib import Path

voices = [Path(sys.argv[1]), Path(sys.argv[2])]
image = Path(sys.argv[3])

for out in voices:
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b''.join(struct.pack('<h', 0) for _ in range(16000)))

image.parent.mkdir(parents=True, exist_ok=True)
# tiny valid PNG header + IHDR/IEND for deterministic fixture
image.write_bytes(
    bytes.fromhex(
        '89504E470D0A1A0A'
        '0000000D4948445200000001000000010802000000907753DE'
        '0000000A49444154789C6360000000020001E221BC330000000049454E44AE426082'
    )
)
PY

set +e
"$BIN_PATH" --mode inspect --project "$PROJECT_DIR" --images "$IMAGES_DIR" --voices "$VOICES_DIR" > "$OUTDIR/mismatch_stdout.txt" 2> "$OUTDIR/mismatch_stderr.txt"
EXIT_CODE=$?
set -e
printf '%s\n' "$EXIT_CODE" > "$OUTDIR/mismatch_exit_code.txt"

if [[ "$EXIT_CODE" -eq 0 ]]; then
  echo "MISMATCH_CONTRACT_FAIL: expected non-zero exit code" > "$OUTDIR/mismatch_check.txt"
  exit 4
fi

if ! grep -Fq "Image/voice count mismatch:" "$OUTDIR/mismatch_stderr.txt"; then
  echo "MISMATCH_CONTRACT_FAIL: missing expected error text" > "$OUTDIR/mismatch_check.txt"
  exit 5
fi

echo "MISMATCH_CONTRACT_OK" > "$OUTDIR/mismatch_check.txt"

find "$OUTDIR" -maxdepth 3 -type f | sort > "$OUTDIR/artifact_list.txt"
sha256sum "$OUTDIR"/*.txt "$OUTDIR"/verify_output/* > "$OUTDIR/evidence_sha256.txt"

cat <<REPORT
CONTRACT_OK
archive=$(realpath "$ARCHIVE")
binary=$BIN_PATH
output_dir=$OUTDIR
REPORT
