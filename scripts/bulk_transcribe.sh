#!/bin/bash
# Bulk-transcribes every audio file in AUDIO_DIR with whisper-cpp and writes
# ready-to-use .md transcripts (in this site's frontmatter format) into
# TRANSCRIPT_DIR. Safe to re-run: any episode that already has a .md file
# in TRANSCRIPT_DIR is skipped, so you can stop and resume freely.
#
# Usage:
#   ./scripts/bulk_transcribe.sh
#
# Requires: brew install whisper-cpp ffmpeg
# And a ggml model downloaded to the path set in MODEL below.

set -euo pipefail

# Paths below are relative to the project root -- run this script from
# the project's root folder (e.g. `./scripts/bulk_transcribe.sh`), not
# from inside /scripts or anywhere else.
AUDIO_DIR="audio"
TRANSCRIPT_DIR="transcripts"
MODEL="$HOME/whisper-models/ggml-medium.en.bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TRANSCRIPT_DIR"

HF_TOKEN="${HF_TOKEN:-}"
SPEAKER_MAP="${SPEAKER_MAP:-}"

if [ -z "$HF_TOKEN" ]; then
  echo "HF_TOKEN is not set. Speaker diarization needs a Hugging Face token."
  echo "See the setup steps at the top of scripts/diarize_and_transcribe.py"
  exit 1
fi

if [ ! -f "$MODEL" ]; then
  echo "Model not found at $MODEL"
  echo "Download one first, e.g.:"
  echo '  mkdir -p ~/whisper-models && curl -L -o ~/whisper-models/ggml-medium.en.bin \'
  echo '    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin?download=true"'
  exit 1
fi

# Recent whisper.cpp releases renamed the CLI binary from whisper-cpp to
# whisper-cli. Detect whichever is actually on PATH so this keeps working
# across versions.
if command -v whisper-cli >/dev/null 2>&1; then
  WHISPER_BIN="whisper-cli"
elif command -v whisper-cpp >/dev/null 2>&1; then
  WHISPER_BIN="whisper-cpp"
else
  echo "Neither whisper-cli nor whisper-cpp found on PATH."
  echo "Check the install with: brew list whisper-cpp"
  echo "(that command lists the actual binary name/path it installed)"
  exit 1
fi
echo "Using $WHISPER_BIN"

shopt -s nullglob
audio_files=("$AUDIO_DIR"/*.mp3 "$AUDIO_DIR"/*.m4a "$AUDIO_DIR"/*.wav)

if [ ${#audio_files[@]} -eq 0 ]; then
  echo "No audio files found in $AUDIO_DIR"
  exit 1
fi

echo "Found ${#audio_files[@]} audio file(s)."

count=0
for audio in "${audio_files[@]}"; do
  base="$(basename "${audio%.*}")"
  out_md="$TRANSCRIPT_DIR/${base}.md"

  if [ -f "$out_md" ]; then
    echo "  [skip] $base (transcript already exists)"
    continue
  fi

  count=$((count + 1))
  echo "  [$count] Transcribing: $base"

  wav="$TMP_DIR/${base}.wav"
  ffmpeg -y -i "$audio" -ar 16000 -ac 1 "$wav" -loglevel error

  "$WHISPER_BIN" -m "$MODEL" -f "$wav" -osrt -of "$TMP_DIR/${base}" -np -pp > /dev/null

  python3 "$SCRIPT_DIR/diarize_and_transcribe.py" \
    "$wav" "$TMP_DIR/${base}.srt" "$out_md" \
    --hf-token "$HF_TOKEN" \
    --speaker-map "$SPEAKER_MAP"

  rm -f "$wav" "$TMP_DIR/${base}.srt"
done

echo "Done. Transcribed $count new episode(s) into $TRANSCRIPT_DIR"
