#!/usr/bin/env python3
"""
Runs the whole pipeline directly from a podcast RSS feed, one episode at a
time: download -> transcribe -> (diarize) -> write the .md -> git commit +
push -> delete the audio -> next episode. At most one episode's audio is on
disk at any point, and the website updates after every finished episode.

Usage:
  python3 scripts/stream_transcribe.py              # uses feed_url from site.config.json
  python3 scripts/stream_transcribe.py "https://example.com/feed.xml"

Useful options:
  --dry-run       List what would be processed, do nothing.
  --limit 5       Only process 5 pending episodes this run.
  --keep-audio    Don't delete audio after transcribing.
  --no-push       Don't git commit/push each transcript (overrides auto_push).
  --speaker-map "SPEAKER_00=HOST,SPEAKER_01=GUEST"
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    git_publish,
    load_config,
    slugify,
    strip_number_prefix,
)
from fetch_rss_episodes import (  # noqa: E402
    add_common_feed_args,
    audio_extension,
    build_existing_title_index,
    download,
    find_existing_match,
    load_feed_items,
    resolve_feed_url,
    write_sidecar,
)
from pipeline import check_prerequisites, transcribe_one  # noqa: E402


def main():
    config = load_config()
    parser = argparse.ArgumentParser()
    add_common_feed_args(parser)
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN", ""))
    parser.add_argument("--speaker-map", default=os.environ.get("SPEAKER_MAP") or config["speaker_map"])
    parser.add_argument("--keep-audio", action="store_true",
                        help="Keep the downloaded audio instead of deleting it after transcribing.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process this many pending episodes, then stop.")
    parser.add_argument("--push", action=argparse.BooleanOptionalAction,
                        default=bool(config["auto_push"]),
                        help="git commit + push each transcript as soon as it's written "
                             "(default from auto_push in site.config.json).")
    args = parser.parse_args()

    feed_url = resolve_feed_url(args.feed_url, config)
    if not args.dry_run:
        whisper_bin, model = check_prerequisites(config, args.hf_token)

    audio_dir = Path(args.audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir = Path(args.transcript_dir)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    items = load_feed_items(feed_url, args.newest_first)
    existing_index = build_existing_title_index(audio_dir, transcript_dir)
    print(f"{len(existing_index)} episode(s) already accounted for (audio or transcript).")

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

        print(f"\n[{i}/{len(items)}] {item['title']}")
        audio_path = audio_dir / f"{filename_base}{audio_extension(item['url'])}"
        meta = {"episode": i, "title": item["title"], "date": item["date"]}

        try:
            print("  Downloading audio...")
            download(item["url"], audio_path)
            transcribe_one(audio_path, out_md, meta, config, args.hf_token,
                           args.speaker_map, whisper_bin, model)
            existing_index[slugify(strip_number_prefix(filename_base))] = out_md.name
        except (Exception, KeyboardInterrupt) as e:
            out_md.unlink(missing_ok=True)
            if isinstance(e, KeyboardInterrupt):
                print("\nInterrupted. Re-run to resume where you left off.", file=sys.stderr)
                sys.exit(130)
            print(f"  FAILED: {e}", file=sys.stderr)
            print(f"  Audio kept at {audio_path} for debugging/retry.", file=sys.stderr)
            failed += 1
            continue

        if args.push:
            git_publish([out_md], f"Add transcript: Ep. {i} - {item['title']}")

        if args.keep_audio:
            write_sidecar(audio_path, i, item)
        else:
            audio_path.unlink(missing_ok=True)
            print("  Removed downloaded audio to save space.")

        processed += 1

    verb = "Would process" if args.dry_run else "Processed"
    print(f"\nDone. {verb} {processed} episode(s), {failed} failed.")


if __name__ == "__main__":
    main()
