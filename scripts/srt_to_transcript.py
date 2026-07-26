#!/usr/bin/env python3
"""
Converts a whisper-cpp .srt file into a .md transcript with the frontmatter
this site expects (episode, title, date, guests, duration) plus
[MM:SS] SPEAKER: text lines.

whisper-cpp does not do speaker diarization, so every line is tagged with a
single placeholder speaker (default "SPEAKER"). If it's a solo show, pass
--speaker HOST to label it properly. If there are multiple speakers, you'll
want to either re-run with a diarization tool (pyannote-audio, or a hosted
option like AssemblyAI/Deepgram that returns speaker + timestamps together)
or hand-edit the speaker labels afterward -- the .md format is plain text,
easy to fix in any editor.

Usage:
  python3 srt_to_transcript.py input.srt output.md [--speaker HOST] [--episode N] [--title "Title"] [--date YYYY-MM-DD]
"""
import argparse
import re
import sys
from pathlib import Path

SRT_BLOCK = re.compile(
    r"\d+\s*\n"
    r"(\d{2}):(\d{2}):(\d{2}),\d{3}\s*-->\s*(\d{2}):(\d{2}):(\d{2}),\d{3}\s*\n"
    r"(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


def parse_srt(srt_text: str):
    """Returns a list of (start_seconds, text) tuples."""
    entries = []
    for m in SRT_BLOCK.finditer(srt_text.strip() + "\n\n"):
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start_seconds = h * 3600 + mi * 60 + s
        text = " ".join(line.strip() for line in m.group(7).strip().splitlines())
        text = text.strip()
        if text:
            entries.append((start_seconds, text))
    return entries


def format_timestamp(total_seconds: int) -> str:
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def guess_episode_title(stem: str):
    """Best-effort parse of '001-my-episode-title' style filenames."""
    m = re.match(r"^0*(\d+)[-_. ]+(.+)$", stem)
    if m:
        episode = m.group(1)
        title_slug = m.group(2)
    else:
        episode = "?"
        title_slug = stem
    title = re.sub(r"[-_]+", " ", title_slug).strip().title()
    return episode, title


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("srt_path")
    parser.add_argument("out_path")
    parser.add_argument("--speaker", default="SPEAKER")
    parser.add_argument("--episode")
    parser.add_argument("--title")
    parser.add_argument("--date", default="")
    parser.add_argument("--guests", default="none")
    args = parser.parse_args()

    srt_path = Path(args.srt_path)
    out_path = Path(args.out_path)

    if not srt_path.exists():
        print(f"whisper-cpp did not produce {srt_path} -- check it ran successfully.", file=sys.stderr)
        sys.exit(1)

    entries = parse_srt(srt_path.read_text(encoding="utf-8"))
    if not entries:
        print(f"No segments parsed from {srt_path} -- transcript may be empty.", file=sys.stderr)

    guessed_episode, guessed_title = guess_episode_title(srt_path.stem)
    episode = args.episode or guessed_episode
    title = args.title or guessed_title
    duration = format_timestamp(entries[-1][0]) if entries else ""

    lines = [f"[{format_timestamp(t)}] {args.speaker}: {text}" for t, text in entries]

    frontmatter = (
        "---\n"
        f"episode: {episode}\n"
        f"title: {title}\n"
        f"date: {args.date}\n"
        f"guests: {args.guests}\n"
        f"duration: {duration}\n"
        "---\n\n"
    )

    out_path.write_text(frontmatter + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} ({len(entries)} lines)")


if __name__ == "__main__":
    main()
