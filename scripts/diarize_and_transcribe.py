#!/usr/bin/env python3
"""
Runs pyannote speaker diarization on a WAV file and merges it with a
whisper-cpp .srt transcript, producing a .md transcript with real speaker
labels (SPEAKER_00, SPEAKER_01, ...) instead of one placeholder speaker.

One-time setup:
  1. pip3 install pyannote.audio --break-system-packages
     (this pulls in torch -- the first install is a large download)
  2. Create a free Hugging Face account: https://huggingface.co/join
  3. Accept the user agreement on BOTH of these model pages (required once,
     just visiting the page and clicking "Agree" while logged in):
       https://huggingface.co/pyannote/speaker-diarization-3.1
       https://huggingface.co/pyannote/segmentation-3.0
  4. Create a read-access token: https://huggingface.co/settings/tokens
  5. export HF_TOKEN=hf_xxxxxxxx

Usage:
  python3 diarize_and_transcribe.py input.wav input.srt output.md \
      --hf-token "$HF_TOKEN" \
      --speaker-map "SPEAKER_00=HOST,SPEAKER_01=GUEST"

If you don't know which SPEAKER_NN is which yet, omit --speaker-map, look
at the output, then re-run once you know (or just find/replace in the .md
file afterward -- it's plain text).
"""
import argparse
import os
import re
import sys
import warnings
from pathlib import Path

# Some pyannote/torch ops aren't yet implemented on Apple's MPS backend --
# this makes those specific ops silently fall back to CPU instead of
# crashing, while everything else still runs on the GPU.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# pyannote's dependencies (urllib3, torch, speechbrain) print a fair amount
# of deprecation / future-behavior-change noise on every run. None of it
# indicates a problem with this script, so it's silenced for a cleaner
# console. If you're debugging something odd, comment this out to see the
# full warnings again.
warnings.filterwarnings("ignore")

SRT_BLOCK = re.compile(
    r"\d+\s*\n"
    r"(\d{2}):(\d{2}):(\d{2}),\d{3}\s*-->\s*(\d{2}):(\d{2}):(\d{2}),\d{3}\s*\n"
    r"(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


def parse_srt(text: str):
    """Returns a list of (start_seconds, end_seconds, text) tuples."""
    entries = []
    for m in SRT_BLOCK.finditer(text.strip() + "\n\n"):
        h1, mi1, s1, h2, mi2, s2 = (int(g) for g in m.groups()[:6])
        start = h1 * 3600 + mi1 * 60 + s1
        end = h2 * 3600 + mi2 * 60 + s2
        text_line = " ".join(l.strip() for l in m.group(7).strip().splitlines()).strip()
        if text_line:
            entries.append((start, end, text_line))
    return entries


def format_timestamp(total_seconds) -> str:
    h, rem = divmod(int(total_seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def run_diarization(wav_path: str, hf_token: str):
    import torch
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
    )

    if torch.backends.mps.is_available():
        print("Using Apple GPU (MPS) for diarization.")
        pipeline.to(torch.device("mps"))
    else:
        print("MPS not available -- running diarization on CPU.")

    diarization = pipeline(wav_path)
    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append((turn.start, turn.end, speaker))
    return segments


def speaker_for(start, end, diar_segments):
    """Picks the diarization speaker with the most time overlap with [start, end]."""
    best_speaker, best_overlap = None, 0.0
    for d_start, d_end, speaker in diar_segments:
        overlap = min(end, d_end) - max(start, d_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    return best_speaker or "UNKNOWN"


def guess_episode_title(stem: str):
    m = re.match(r"^0*(\d+)[-_. ]+(.+)$", stem)
    if m:
        return m.group(1), re.sub(r"[-_]+", " ", m.group(2)).strip().title()
    return "?", re.sub(r"[-_]+", " ", stem).strip().title()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wav_path")
    parser.add_argument("srt_path")
    parser.add_argument("out_path")
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN", ""))
    parser.add_argument(
        "--speaker-map", default="",
        help='e.g. "SPEAKER_00=HOST,SPEAKER_01=GUEST" -- renames diarization labels',
    )
    parser.add_argument("--episode")
    parser.add_argument("--title")
    parser.add_argument("--date", default="")
    parser.add_argument("--guests", default="none")
    args = parser.parse_args()

    if not args.hf_token:
        print(
            "No Hugging Face token found. Pass --hf-token or set HF_TOKEN.\n"
            "See the setup steps in this script's docstring.",
            file=sys.stderr,
        )
        sys.exit(1)

    srt_path = Path(args.srt_path)
    if not srt_path.exists():
        print(f"SRT file not found: {srt_path}", file=sys.stderr)
        sys.exit(1)

    entries = parse_srt(srt_path.read_text(encoding="utf-8"))
    if not entries:
        print(f"No segments parsed from {srt_path}.", file=sys.stderr)

    print("Running diarization (slower than transcription -- be patient on CPU)...")
    diar_segments = run_diarization(args.wav_path, args.hf_token)

    name_map = {}
    for pair in args.speaker_map.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            name_map[k.strip()] = v.strip()

    lines = []
    speakers_seen = set()
    for start, end, text in entries:
        raw_speaker = speaker_for(start, end, diar_segments)
        speakers_seen.add(raw_speaker)
        speaker = name_map.get(raw_speaker, raw_speaker)
        lines.append(f"[{format_timestamp(start)}] {speaker}: {text}")

    guessed_episode, guessed_title = guess_episode_title(srt_path.stem)
    episode = args.episode or guessed_episode
    title = args.title or guessed_title
    duration = format_timestamp(entries[-1][1]) if entries else ""

    frontmatter = (
        "---\n"
        f"episode: {episode}\n"
        f"title: {title}\n"
        f"date: {args.date}\n"
        f"guests: {args.guests}\n"
        f"duration: {duration}\n"
        "---\n\n"
    )

    Path(args.out_path).write_text(frontmatter + "\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.out_path} ({len(lines)} lines, "
        f"{len(speakers_seen)} distinct speaker(s) detected: {sorted(speakers_seen)})"
    )


if __name__ == "__main__":
    main()
