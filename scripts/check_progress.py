#!/usr/bin/env python3
"""
Shows transcription progress: how many audio files exist, how many already
have a transcript, and which ones are still pending.

Usage:
  python3 scripts/check_progress.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bulk_transcribe import pending_audio  # noqa: E402
from common import AUDIO_DIR, TRANSCRIPT_DIR  # noqa: E402


def main():
    audio, pending = pending_audio(AUDIO_DIR, TRANSCRIPT_DIR)
    transcripts = list(TRANSCRIPT_DIR.glob("*.md"))

    print(f"Transcripts in archive: {len(transcripts)}")
    print(f"Audio files in audio/:  {len(audio)}")
    print(f"  still to transcribe:  {len(pending)}")

    if pending:
        print("\nPending (picked up next time bulk_transcribe.py runs):")
        for p in pending:
            print(f"  - {p.name}")


if __name__ == "__main__":
    main()
