#!/usr/bin/env python3
"""
Downloads episode audio straight from a podcast's RSS feed into audio/,
named to match the numbering convention the rest of this pipeline expects
(NNN-episode-title.ext). Each download also gets a small NNN-....json
sidecar with the episode's real title and release date, which the
transcription step uses for the transcript's frontmatter.

Skips any episode you already have (audio OR transcript, matched by title),
so it's safe to re-run whenever the feed publishes a new episode.

Usage:
  python3 scripts/fetch_rss_episodes.py                 # uses feed_url from site.config.json
  python3 scripts/fetch_rss_episodes.py "https://example.com/feed.xml"

Uses only the Python standard library -- no extra pip installs needed.
"""
import argparse
import difflib
import json
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    AUDIO_DIR,
    AUDIO_EXTENSIONS,
    TRANSCRIPT_DIR,
    load_config,
    normalize_date,
    sidecar_path,
    slugify,
    strip_number_prefix,
)

USER_AGENT = "Mozilla/5.0 (podcast-transcript-archive)"


def build_existing_title_index(audio_dir: Path, transcript_dir: Path = None):
    """Maps a slugified, number-stripped title -> a filename it came from,
    scanning BOTH the audio folder and the transcripts folder. A transcript
    counts as "already have this episode" even if its audio is gone."""
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


def resolve_feed_url(cli_value, config) -> str:
    url = cli_value or config.get("feed_url", "")
    if not url:
        sys.exit("No feed URL given. Pass one on the command line or set "
                 "\"feed_url\" in site.config.json.")
    return url


def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
            parsed.append({"title": title, "url": audio_url, "date": normalize_date(pubdate)})
    return parsed


def audio_extension(url: str) -> str:
    ext = Path(url.split("?")[0]).suffix.lower()
    return ext if ext in AUDIO_EXTENSIONS else ".mp3"


def download(url: str, dest: Path):
    """Streams to a .part file first, so an interrupted download never
    looks like a finished episode on the next run."""
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f)
    tmp.replace(dest)


def write_sidecar(audio_path: Path, episode: int, item: dict):
    sidecar_path(audio_path).write_text(
        json.dumps({"episode": episode, "title": item["title"], "date": item["date"]}, indent=2),
        encoding="utf-8",
    )


def load_feed_items(feed_url: str, newest_first: bool):
    print(f"Fetching feed: {feed_url}")
    try:
        items = parse_items(fetch_feed(feed_url))
    except ET.ParseError as e:
        sys.exit(f"Failed to parse feed XML: {e}")
    except Exception as e:
        sys.exit(f"Failed to fetch feed: {e}")
    if not items:
        sys.exit("No episodes with audio enclosures found in this feed.")
    if not newest_first:
        items = list(reversed(items))
    print(f"Found {len(items)} episode(s) in feed.")
    return items


def add_common_feed_args(parser):
    parser.add_argument("feed_url", nargs="?",
                        help="RSS feed URL (defaults to feed_url in site.config.json)")
    parser.add_argument("--audio-dir", default=str(AUDIO_DIR))
    parser.add_argument("--transcript-dir", default=str(TRANSCRIPT_DIR))
    parser.add_argument(
        "--newest-first", action="store_true",
        help="Keep the feed's native newest-first order instead of reversing "
             "it. By default episode 001 = the oldest/first-released episode.",
    )
    parser.add_argument(
        "--match-threshold", type=float, default=0.82,
        help="Similarity threshold (0-1) for treating a feed title as matching "
             "an existing file. Lower catches more dupes but risks false positives.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without downloading anything.")


def main():
    parser = argparse.ArgumentParser()
    add_common_feed_args(parser)
    args = parser.parse_args()

    feed_url = resolve_feed_url(args.feed_url, load_config())
    audio_dir = Path(args.audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir = Path(args.transcript_dir)

    items = load_feed_items(feed_url, args.newest_first)

    existing_index = build_existing_title_index(audio_dir, transcript_dir)
    audio_count = sum(1 for v in existing_index.values() if not v.startswith("transcript: "))
    print(
        f"Found {audio_count} existing audio file(s) in {audio_dir} "
        f"and {len(existing_index) - audio_count} existing transcript(s) in {transcript_dir}"
    )

    downloaded, skipped, failed = 0, 0, 0
    for i, item in enumerate(items, start=1):
        slug = slugify(item["title"])
        filename = f"{i:03d}-{slug}{audio_extension(item['url'])}"

        match = find_existing_match(slug, existing_index, args.match_threshold)
        if match:
            print(f"  [{i}/{len(items)}] Skip: '{item['title']}' matches existing file '{match}'")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [{i}/{len(items)}] Would download: {filename}")
            downloaded += 1
            continue

        target = audio_dir / filename
        print(f"  [{i}/{len(items)}] Downloading: {filename}")
        try:
            download(item["url"], target)
            write_sidecar(target, i, item)
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
