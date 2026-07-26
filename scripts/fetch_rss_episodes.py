#!/usr/bin/env python3
"""
Downloads episode audio straight from a podcast's RSS feed into the audio
folder, named to match the numbering convention the rest of this pipeline
expects (NNN-episode-title.ext).

Skips any episode whose target file already exists, so it's safe to re-run
whenever the feed publishes a new episode -- it'll only fetch what's new.

Usage:
  python3 scripts/fetch_rss_episodes.py "https://example.com/feed.xml"

Uses only the Python standard library -- no extra pip installs needed.
"""
import argparse
import difflib
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Defaults are relative to the project root -- run this from the
# project's root folder (e.g. `python3 scripts/fetch_rss_episodes.py ...`).
DEFAULT_AUDIO_DIR = Path("audio")
DEFAULT_TRANSCRIPT_DIR = Path("transcripts")
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "untitled"


def strip_number_prefix(stem: str) -> str:
    """Strips a leading '001-', '12_', '3.', etc. from a filename stem."""
    m = re.match(r"^0*\d+[-_. ]+(.+)$", stem)
    return m.group(1) if m else stem


def build_existing_title_index(audio_dir: Path, transcript_dir: Path = None):
    """Maps a slugified, number-stripped title -> a filename it came from,
    scanning BOTH the audio folder and the transcripts folder. A transcript
    counts as "already have this episode" even if its original audio file
    isn't around anymore (renamed, moved, cleaned up, etc)."""
    index = {}

    if audio_dir.exists():
        for p in audio_dir.iterdir():
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS:
                index[slugify(strip_number_prefix(p.stem))] = p.name

    if transcript_dir and transcript_dir.exists():
        for p in transcript_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".md":
                key = slugify(strip_number_prefix(p.stem))
                index.setdefault(key, f"transcript: {p.name}")

    return index


def find_existing_match(slug: str, existing_index: dict, threshold: float = 0.82):
    """Returns the matching existing filename if this slug looks like an
    episode we already have (exact match, substring match, or close enough
    by similarity ratio), else None."""
    if slug in existing_index:
        return existing_index[slug]
    for existing_slug, filename in existing_index.items():
        if slug in existing_slug or existing_slug in slug:
            return filename
        if difflib.SequenceMatcher(None, slug, existing_slug).ratio() >= threshold:
            return filename
    return None


def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse_items(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall(".//item")

    parsed = []
    for item in items:
        title_el = item.find("title")
        title = title_el.text.strip() if title_el is not None and title_el.text else "untitled"

        enclosure = item.find("enclosure")
        audio_url = enclosure.get("url") if enclosure is not None else None

        pubdate_el = item.find("pubDate")
        pubdate = pubdate_el.text.strip() if pubdate_el is not None and pubdate_el.text else ""

        if audio_url:
            parsed.append({"title": title, "url": audio_url, "pubdate": pubdate})
    return parsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("feed_url")
    parser.add_argument("--audio-dir", default=str(DEFAULT_AUDIO_DIR))
    parser.add_argument("--transcript-dir", default=str(DEFAULT_TRANSCRIPT_DIR))
    parser.add_argument(
        "--newest-first",
        action="store_true",
        help="Keep the feed's native newest-first order instead of "
             "reversing it. By default episodes are reversed so episode "
             "001 = the oldest/first-released episode.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded/skipped without downloading anything.",
    )
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=0.82,
        help="Similarity threshold (0-1) for treating a feed title as matching "
             "an existing file when it's not an exact or substring match. "
             "Lower catches more potential dupes but risks false positives.",
    )
    args = parser.parse_args()

    audio_dir = Path(args.audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir = Path(args.transcript_dir)

    print(f"Fetching feed: {args.feed_url}")
    try:
        xml_bytes = fetch_feed(args.feed_url)
    except Exception as e:
        print(f"Failed to fetch feed: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        items = parse_items(xml_bytes)
    except ET.ParseError as e:
        print(f"Failed to parse feed XML: {e}", file=sys.stderr)
        sys.exit(1)

    if not items:
        print("No episodes with audio enclosures found in this feed.", file=sys.stderr)
        sys.exit(1)

    if not args.newest_first:
        items = list(reversed(items))

    print(f"Found {len(items)} episode(s) in feed.")

    existing_index = build_existing_title_index(audio_dir, transcript_dir)
    audio_count = sum(1 for v in existing_index.values() if not v.startswith("transcript: "))
    transcript_count = len(existing_index) - audio_count
    print(
        f"Found {audio_count} existing audio file(s) in {audio_dir} "
        f"and {transcript_count} existing transcript(s) in {transcript_dir}"
    )

    downloaded, skipped, failed = 0, 0, 0
    for i, item in enumerate(items, start=1):
        slug = slugify(item["title"])
        ext = Path(item["url"].split("?")[0]).suffix or ".mp3"
        filename = f"{i:03d}-{slug}{ext}"

        match = find_existing_match(slug, existing_index, args.match_threshold)
        if match:
            print(f"  [{i}/{len(items)}] Skip: '{item['title']}' matches existing file '{match}'")
            skipped += 1
            continue

        target = audio_dir / filename
        if target.exists():
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [{i}/{len(items)}] Would download: {filename}")
            downloaded += 1
            continue

        print(f"  [{i}/{len(items)}] Downloading: {filename}")
        try:
            req = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = resp.read()
            target.write_bytes(data)
            downloaded += 1
            # Register it immediately so later items in this same feed
            # can't accidentally re-match/duplicate against it.
            existing_index[slugify(strip_number_prefix(target.stem))] = target.name
        except Exception as e:
            print(f"    Failed: {e}", file=sys.stderr)
            failed += 1

    verb = "Would download" if args.dry_run else "Downloaded"
    print(
        f"\nDone. {verb} {downloaded} new episode(s), "
        f"skipped {skipped} already present, {failed} failed."
    )


if __name__ == "__main__":
    main()
