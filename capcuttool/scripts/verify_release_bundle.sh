#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <archive.tar.gz> [workdir]" >&2
  exit 1
fi

ARCHIVE="$1"
WORKDIR="${2:-$(mktemp -d)}"
OUTDIR="$WORKDIR/verify_output"
mkdir -p "$OUTDIR"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Archive not found: $ARCHIVE" >&2
  exit 2
fi

ARCHIVE_ABS="$(realpath "$ARCHIVE")"
BASENAME="$(basename "$ARCHIVE")"

sha256sum "$ARCHIVE_ABS" > "$OUTDIR/archive.sha256"

tar -xzf "$ARCHIVE_ABS" -C "$WORKDIR"

BIN_PATH="$(find "$WORKDIR" -maxdepth 3 -type f -name capcut_adapter | head -n 1 || true)"
if [[ -z "$BIN_PATH" ]]; then
  echo "capcut_adapter binary not found after extract" >&2
  exit 3
fi

sha256sum "$BIN_PATH" > "$OUTDIR/binary.sha256"
file "$BIN_PATH" > "$OUTDIR/binary.filetype.txt"
"$BIN_PATH" --help > "$OUTDIR/smoke_help.txt"

cat <<REPORT
VERIFY_OK
archive=$ARCHIVE_ABS
binary=$BIN_PATH
output_dir=$OUTDIR
REPORT
