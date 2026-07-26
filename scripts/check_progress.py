#!/usr/bin/env python3
"""
Shows transcription progress: how many audio files exist, how many already
have a transcript, and which ones are still pending. Handy for confirming
exactly where a paused batch run left off before resuming.

Usage:
  python3 scripts/check_progress.py
"""
from pathlib import Path

# Paths are relative to the project root -- run this from the project's
# root folder (e.g. `python3 scripts/check_progress.py`).
AUDIO_DIR = Path("audio")
TRANSCRIPT_DIR = Path("transcripts")

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}


def main():
    if not AUDIO_DIR.exists():
        print(f"Audio directory not found: {AUDIO_DIR}")
        return

    audio_files = sorted(
        p for p in AUDIO_DIR.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS
    )

    done, pending = [], []
    for audio in audio_files:
        transcript = TRANSCRIPT_DIR / f"{audio.stem}.md"
        (done if transcript.exists() else pending).append(audio.name)

    print(f"Total audio files:  {len(audio_files)}")
    print(f"Transcribed:        {len(done)}")
    print(f"Remaining:          {len(pending)}")

    if pending:
        print("\nPending (will be picked up next time bulk_transcribe.sh runs):")
        for name in pending:
            print(f"  - {name}")
    elif audio_files:
        print("\nAll episodes transcribed.")


if __name__ == "__main__":
    main()
