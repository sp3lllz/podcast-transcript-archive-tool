"""
The single-episode pipeline shared by bulk_transcribe.py and
stream_transcribe.py: audio -> 16kHz WAV (ffmpeg) -> .srt (whisper-cpp) ->
speaker labels (pyannote, optional) -> .md transcript.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import model_path, parse_srt, render_transcript
from diarize_and_transcribe import label_speakers


def find_whisper_binary():
    # Recent whisper.cpp releases renamed the CLI from whisper-cpp to whisper-cli.
    for name in ("whisper-cli", "whisper-cpp"):
        if shutil.which(name):
            return name
    return None


def check_prerequisites(config: dict, hf_token: str):
    """Exits with a helpful message if anything needed is missing.
    Returns (whisper_bin, model)."""
    problems = []
    whisper_bin = find_whisper_binary()
    if not whisper_bin:
        problems.append("whisper-cpp not found on PATH (install: brew install whisper-cpp)")
    if not shutil.which("ffmpeg"):
        problems.append("ffmpeg not found on PATH (install: brew install ffmpeg)")
    model = model_path(config)
    if not model.exists():
        problems.append(f"Whisper model not found at {model} (run: make model)")
    if problems:
        sys.exit("Missing prerequisites:\n  - " + "\n  - ".join(problems))

    if hf_token:
        print("Speaker diarization: ON (pyannote)")
    else:
        print(f"Speaker diarization: OFF -- every line will be labelled "
              f"'{config['default_speaker']}'. Set HF_TOKEN to enable it.")
    return whisper_bin, model


def transcribe_one(audio_path: Path, out_md: Path, meta: dict, config: dict,
                   hf_token: str, speaker_map: str, whisper_bin: str, model: Path):
    """Transcribes one audio file into out_md. meta supplies episode/title/date."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wav_path = tmp / "audio.wav"

        print("  Converting to WAV...")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1",
             str(wav_path), "-loglevel", "error"],
            check=True,
        )

        print("  Transcribing (whisper)...")
        result = subprocess.run(
            [whisper_bin, "-m", str(model), "-f", str(wav_path),
             "-osrt", "-of", str(tmp / "audio"), "-np"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"{whisper_bin} failed:\n{result.stderr.strip()[-2000:]}")

        entries = parse_srt((tmp / "audio.srt").read_text(encoding="utf-8"))
        speakers = label_speakers(entries, wav_path, hf_token, speaker_map,
                                  config["default_speaker"])

    out_md.write_text(
        render_transcript(entries, speakers, meta["episode"], meta["title"],
                          meta.get("date", ""), meta.get("guests", "none")),
        encoding="utf-8",
    )
    print(f"  Wrote {out_md.name} ({len(entries)} lines)")
