#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <workdir>" >&2
  exit 1
fi

WORKDIR="$1"
mkdir -p "$WORKDIR"
OUTDIR="$WORKDIR/partial_index_source_contract"
mkdir -p "$OUTDIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

python3 - <<'PY' "$IMAGES_DIR/scene_001.png" "$VOICES_DIR/scene.wav"
import struct
import sys
import wave
from pathlib import Path

image = Path(sys.argv[1])
voice = Path(sys.argv[2])

image.parent.mkdir(parents=True, exist_ok=True)
image.write_bytes(
    bytes.fromhex(
        '89504E470D0A1A0A'
        '0000000D4948445200000001000000010802000000907753DE'
        '0000000A49444154789C6360000000020001E221BC330000000049454E44AE426082'
    )
)

voice.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(voice), 'wb') as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes(b''.join(struct.pack('<h', 0) for _ in range(16000)))
PY

set +e
python3 "$REPO_DIR/cli.py" --mode inspect --project "$PROJECT_DIR" --images "$IMAGES_DIR" --voices "$VOICES_DIR" > "$OUTDIR/partial_index_stdout.txt" 2> "$OUTDIR/partial_index_stderr.txt"
EXIT_CODE=$?
set -e
printf '%s\n' "$EXIT_CODE" > "$OUTDIR/partial_index_exit_code.txt"

if [[ "$EXIT_CODE" -eq 0 ]]; then
  echo "PARTIAL_INDEX_CONTRACT_FAIL: expected non-zero exit code" > "$OUTDIR/partial_index_check.txt"
  exit 4
fi

if ! grep -Fq "Inconsistent scene naming:" "$OUTDIR/partial_index_stderr.txt"; then
  echo "PARTIAL_INDEX_CONTRACT_FAIL: missing expected error text" > "$OUTDIR/partial_index_check.txt"
  exit 5
fi

echo "PARTIAL_INDEX_CONTRACT_OK" > "$OUTDIR/partial_index_check.txt"

find "$OUTDIR" -maxdepth 4 -type f | sort > "$OUTDIR/artifact_list.txt"
sha256sum "$OUTDIR"/*.txt > "$OUTDIR/evidence_sha256.txt"

cat <<REPORT
CONTRACT_OK
output_dir=$OUTDIR
REPORT
