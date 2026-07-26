#!/usr/bin/env python3
"""
Streams the whole pipeline directly from a podcast RSS feed, one episode at
a time: downloads a single episode's audio, transcribes it (whisper-cli),
diarizes it (pyannote), writes the finished .md transcript, then deletes
the downloaded audio before moving to the next episode. At most one
episode's audio exists on disk at any point, instead of the whole backlog.

One-time setup is the same as bulk_transcribe.sh -- whisper-cli (Homebrew),
a downloaded ggml model, ffmpeg, and the pyannote.audio virtual environment
+ HF_TOKEN for diarization. See the README for all of that.

Usage:
  source ~/whisper-env/bin/activate
  export HF_TOKEN=hf_xxxxxxxx
  python3 scripts/stream_transcribe.py "https://example.com/feed.xml"

Useful options:
  --dry-run                 List what would be processed, do nothing.
  --limit 5                 Only process 5 pending episodes this run.
  --keep-audio               Don't delete audio after transcribing.
  --speaker-map "SPEAKER_00=HOST,SPEAKER_01=GUEST"
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_rss_episodes import (  # noqa: E402
    fetch_feed,
    parse_items,
    slugify,
    strip_number_prefix,
    build_existing_title_index,
    find_existing_match,
)
from diarize_and_transcribe import (  # noqa: E402
    parse_srt,
    run_diarization,
    speaker_for,
    format_timestamp,
)

# Audio/transcript defaults are relative to the project root -- run this
# from the project's root folder. The model stays under the user's home
# directory since it's a large shared file, not something per-project.
DEFAULT_AUDIO_DIR = Path("audio")
DEFAULT_TRANSCRIPT_DIR = Path("transcripts")
DEFAULT_MODEL = Path.home() / "whisper-models" / "ggml-medium.en.bin"


def find_whisper_binary():
    for name in ("whisper-cli", "whisper-cpp"):
        if shutil.which(name):
            return name
    return None


def download(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        dest.write_bytes(resp.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("feed_url")
    parser.add_argument("--audio-dir", default=str(DEFAULT_AUDIO_DIR))
    parser.add_argument("--transcript-dir", default=str(DEFAULT_TRANSCRIPT_DIR))
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN", ""))
    parser.add_argument("--speaker-map", default=os.environ.get("SPEAKER_MAP", ""))
    parser.add_argument("--newest-first", action="store_true")
    parser.add_argument("--match-threshold", type=float, default=0.82)
    parser.add_argument(
        "--keep-audio", action="store_true",
        help="Keep the downloaded audio file instead of deleting it after transcribing.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only process this many pending episodes, then stop.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be processed without downloading or transcribing anything.",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.hf_token:
        print("HF_TOKEN is not set. Diarization needs a Hugging Face token.", file=sys.stderr)
        sys.exit(1)

    whisper_bin = find_whisper_binary()
    if not args.dry_run and not whisper_bin:
        print("Neither whisper-cli nor whisper-cpp found on PATH.", file=sys.stderr)
        sys.exit(1)

    model_path = Path(args.model)
    if not args.dry_run and not model_path.exists():
        print(f"Model not found at {model_path}", file=sys.stderr)
        sys.exit(1)

    audio_dir = Path(args.audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir = Path(args.transcript_dir)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching feed: {args.feed_url}")
    xml_bytes = fetch_feed(args.feed_url)
    items = parse_items(xml_bytes)
    if not items:
        print("No episodes with audio enclosures found in this feed.", file=sys.stderr)
        sys.exit(1)
    if not args.newest_first:
        items = list(reversed(items))
    print(f"Found {len(items)} episode(s) in feed.")

    existing_index = build_existing_title_index(audio_dir, transcript_dir)
    print(f"{len(existing_index)} episode(s) already accounted for (audio or transcript).")

    name_map = {}
    for pair in args.speaker_map.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            name_map[k.strip()] = v.strip()

    processed, failed = 0, 0
    for i, item in enumerate(items, start=1):
        if args.limit is not None and processed >= args.limit:
            print(f"Reached --limit {args.limit}, stopping.")
            break

        slug = slugify(item["title"])
        if find_existing_match(slug, existing_index, args.match_threshold):
            continue  # already have it -- normal steady-state, no need to log every skip

        filename_base = f"{i:03d}-{slug}"
        out_md = transcript_dir / f"{filename_base}.md"

        if args.dry_run:
            print(f"  [{i}/{len(items)}] Would process: {item['title']}")
            processed += 1
            continue

        print(f"\n[{i}/{len(items)}] Processing: {item['title']}")
        ext = Path(item["url"].split("?")[0]).suffix or ".mp3"
        audio_path = audio_dir / f"{filename_base}{ext}"

        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                wav_path = tmp / f"{filename_base}.wav"
                srt_path = tmp / f"{filename_base}.srt"

                print("  Downloading audio...")
                download(item["url"], audio_path)

                print("  Converting to WAV...")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1",
                     str(wav_path), "-loglevel", "error"],
                    check=True,
                )

                print("  Transcribing...")
                subprocess.run(
                    [whisper_bin, "-m", str(model_path), "-f", str(wav_path),
                     "-osrt", "-of", str(tmp / filename_base), "-np", "-pp"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )

                print("  Diarizing (slower than transcription)...")
                entries = parse_srt(srt_path.read_text(encoding="utf-8"))
                diar_segments = run_diarization(str(wav_path), args.hf_token)

                lines = []
                speakers_seen = set()
                for start, end, text in entries:
                    raw_speaker = speaker_for(start, end, diar_segments)
                    speakers_seen.add(raw_speaker)
                    speaker = name_map.get(raw_speaker, raw_speaker)
                    lines.append(f"[{format_timestamp(start)}] {speaker}: {text}")

                duration = format_timestamp(entries[-1][1]) if entries else ""
                frontmatter = (
                    "---\n"
                    f"episode: {i}\n"
                    f"title: {item['title']}\n"
                    f"date: {item.get('pubdate', '')}\n"
                    "guests: none\n"
                    f"duration: {duration}\n"
                    "---\n\n"
                )
                out_md.write_text(frontmatter + "\n".join(lines) + "\n", encoding="utf-8")
                print(f"  Wrote {out_md} ({len(lines)} lines, {len(speakers_seen)} speaker(s))")

                existing_index[slugify(strip_number_prefix(filename_base))] = out_md.name

            if not args.keep_audio:
                audio_path.unlink(missing_ok=True)
                print("  Removed downloaded audio to save space.")

            processed += 1

        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            print(f"  Audio kept at {audio_path} for debugging/retry.", file=sys.stderr)
            failed += 1
            continue

    verb = "Would process" if args.dry_run else "Processed"
    print(f"\nDone. {verb} {processed} episode(s), {failed} failed.")


if __name__ == "__main__":
    main()
