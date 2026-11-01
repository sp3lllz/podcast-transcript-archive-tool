#!/usr/bin/env python3
"""
Turns a whisper-cpp .srt (plus the matching 16kHz WAV) into a finished .md
transcript in this site's format.

If a Hugging Face token is available (HF_TOKEN or --hf-token), speakers are
identified with pyannote diarization (SPEAKER_00, SPEAKER_01, ...). Without
one -- or with --no-diarize -- every line gets the single `default_speaker`
label from site.config.json, which is fine for solo shows and much faster.

One-time setup for diarization (optional):
  1. pip install -r requirements.txt   (inside the project's .venv)
  2. Create a free Hugging Face account: https://huggingface.co/join
  3. Accept the user agreement on BOTH of these model pages:
       https://huggingface.co/pyannote/speaker-diarization-3.1
       https://huggingface.co/pyannote/segmentation-3.0
  4. Create a read-access token: https://huggingface.co/settings/tokens
  5. export HF_TOKEN=hf_xxxxxxxx

Usage:
  python3 scripts/diarize_and_transcribe.py input.wav input.srt output.md \
      [--speaker-map "SPEAKER_00=HOST,SPEAKER_01=GUEST"] [--publish]

Episode number, title and date default to the audio's metadata sidecar
(written by fetch_rss_episodes.py) or are guessed from the filename.
"""
import argparse
import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    git_publish,
    guess_episode_title,
    load_config,
    parse_speaker_map,
    parse_srt,
    read_sidecar,
    render_transcript,
)

# Some pyannote/torch ops aren't yet implemented on Apple's MPS backend --
# this makes those specific ops fall back to CPU instead of crashing.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# pyannote's dependencies print a lot of deprecation noise on every run.
# None of it indicates a problem; comment this out when debugging.
warnings.filterwarnings("ignore")


def run_diarization(wav_path: str, hf_token: str):
    import torch
    from pyannote.audio import Pipeline

    try:  # pyannote.audio 4.x
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=hf_token)
    except TypeError:  # pyannote.audio 3.x
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
        )
    if pipeline is None:
        raise RuntimeError(
            "Could not load the pyannote pipeline. Check HF_TOKEN and that you "
            "accepted the terms on both pyannote model pages."
        )

    if torch.backends.mps.is_available():
        print("  Using Apple GPU (MPS) for diarization.")
        pipeline.to(torch.device("mps"))
    elif torch.cuda.is_available():
        print("  Using CUDA GPU for diarization.")
        pipeline.to(torch.device("cuda"))
    else:
        print("  No GPU available -- running diarization on CPU (slow).")

    output = pipeline(wav_path)
    annotation = getattr(output, "speaker_diarization", output)  # 4.x wraps it
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def speaker_for(start, end, diar_segments):
    """Picks the diarization speaker with the most time overlap with [start, end]."""
    best_speaker, best_overlap = None, 0.0
    for d_start, d_end, speaker in diar_segments:
        overlap = min(end, d_end) - max(start, d_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    return best_speaker or "UNKNOWN"


def label_speakers(entries, wav_path, hf_token, speaker_map, default_speaker):
    """Returns one speaker label per SRT entry."""
    if not hf_token:
        return [default_speaker] * len(entries)
    print("  Diarizing (slower than transcription)...")
    diar_segments = run_diarization(str(wav_path), hf_token)
    name_map = parse_speaker_map(speaker_map)
    raw = [speaker_for(start, end, diar_segments) for start, end, _ in entries]
    print(f"  {len(set(raw))} distinct speaker(s) detected: {sorted(set(raw))}")
    return [name_map.get(s, s) for s in raw]


def main():
    config = load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("wav_path")
    parser.add_argument("srt_path")
    parser.add_argument("out_path")
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN", ""))
    parser.add_argument("--no-diarize", action="store_true",
                        help="Skip speaker detection even if HF_TOKEN is set.")
    parser.add_argument("--speaker-map", default=os.environ.get("SPEAKER_MAP") or config["speaker_map"],
                        help='e.g. "SPEAKER_00=HOST,SPEAKER_01=GUEST"')
    parser.add_argument("--episode")
    parser.add_argument("--title")
    parser.add_argument("--date")
    parser.add_argument("--guests", default="none")
    parser.add_argument("--publish", action="store_true",
                        help="git commit + push the transcript once written.")
    args = parser.parse_args()

    srt_path = Path(args.srt_path)
    if not srt_path.exists():
        sys.exit(f"SRT file not found: {srt_path} -- check whisper ran successfully.")

    entries = parse_srt(srt_path.read_text(encoding="utf-8"))
    if not entries:
        print(f"No segments parsed from {srt_path} -- transcript will be empty.", file=sys.stderr)

    hf_token = "" if args.no_diarize else args.hf_token
    speakers = label_speakers(entries, args.wav_path, hf_token,
                              args.speaker_map, config["default_speaker"])

    sidecar = read_sidecar(srt_path.stem)
    guessed_episode, guessed_title = guess_episode_title(srt_path.stem)
    episode = args.episode or sidecar.get("episode") or guessed_episode
    title = args.title or sidecar.get("title") or guessed_title
    date = args.date or sidecar.get("date", "")

    out_path = Path(args.out_path)
    out_path.write_text(
        render_transcript(entries, speakers, episode, title, date, args.guests),
        encoding="utf-8",
    )
    print(f"  Wrote {out_path} ({len(entries)} lines)")

    if args.publish:
        git_publish([out_path], f"Add transcript: Ep. {episode} - {title}")


if __name__ == "__main__":
    main()
