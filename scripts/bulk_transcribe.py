#!/usr/bin/env python3
"""
Transcribes every audio file in audio/ that doesn't have a transcript yet,
writing transcripts/<same-name>.md. Each finished transcript is committed and
pushed straight away (if auto_push is on), so the website fills in as the
batch runs. Safe to stop (Ctrl+C) and re-run: finished episodes are skipped.

Usage:
  python3 scripts/bulk_transcribe.py [--no-push] [--limit N]

Episode number/title/date come from the .json sidecar written by
fetch_rss_episodes.py, or are guessed from a 001-episode-title.mp3 filename.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    AUDIO_DIR,
    AUDIO_EXTENSIONS,
    TRANSCRIPT_DIR,
    git_publish,
    guess_episode_title,
    load_config,
    read_sidecar,
)
from pipeline import check_prerequisites, transcribe_one  # noqa: E402


def pending_audio(audio_dir: Path, transcript_dir: Path):
    if not audio_dir.exists():
        return [], []
    audio = sorted(p for p in audio_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)
    pending = [p for p in audio if not (transcript_dir / f"{p.stem}.md").exists()]
    return audio, pending


def main():
    config = load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio-dir", default=str(AUDIO_DIR))
    parser.add_argument("--transcript-dir", default=str(TRANSCRIPT_DIR))
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN", ""))
    parser.add_argument("--speaker-map", default=os.environ.get("SPEAKER_MAP") or config["speaker_map"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--push", action=argparse.BooleanOptionalAction,
                        default=bool(config["auto_push"]),
                        help="git commit + push each transcript as soon as it's written.")
    args = parser.parse_args()

    audio_dir, transcript_dir = Path(args.audio_dir), Path(args.transcript_dir)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    all_audio, pending = pending_audio(audio_dir, transcript_dir)
    if not all_audio:
        sys.exit(f"No audio files found in {audio_dir}")
    print(f"{len(all_audio)} audio file(s), {len(pending)} still to transcribe.")
    if args.limit is not None:
        pending = pending[: args.limit]

    whisper_bin, model = check_prerequisites(config, args.hf_token)

    done, failed = 0, 0
    for n, audio in enumerate(pending, start=1):
        print(f"\n[{n}/{len(pending)}] {audio.name}")
        out_md = transcript_dir / f"{audio.stem}.md"
        guessed_episode, guessed_title = guess_episode_title(audio.stem)
        meta = {"episode": guessed_episode, "title": guessed_title, "date": ""}
        meta.update(read_sidecar(audio.stem))
        try:
            transcribe_one(audio, out_md, meta, config, args.hf_token,
                           args.speaker_map, whisper_bin, model)
        except KeyboardInterrupt:
            out_md.unlink(missing_ok=True)
            sys.exit("\nInterrupted. Re-run to resume where you left off.")
        except Exception as e:
            out_md.unlink(missing_ok=True)
            print(f"  FAILED: {e}", file=sys.stderr)
            failed += 1
            continue
        done += 1
        if args.push:
            git_publish([out_md], f"Add transcript: Ep. {meta['episode']} - {meta['title']}")

    print(f"\nDone. Transcribed {done} episode(s), {failed} failed.")


if __name__ == "__main__":
    main()
