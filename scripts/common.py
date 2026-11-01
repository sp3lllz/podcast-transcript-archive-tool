"""
Shared helpers for the transcription scripts and the site builder: project
paths, site.config.json loading, SRT parsing, transcript formatting and the
git auto-publish step.

Every path here is resolved from the project root (the folder containing
site.config.json), so the scripts work no matter which folder you run them
from.
"""
import email.utils
import json
import re
import subprocess
import sys
from pathlib import Path

# Long batch runs are often piped to a log file; flush each line so the log
# stays in order and shows progress as it happens.
sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"
TRANSCRIPT_DIR = ROOT / "transcripts"
CONFIG_PATH = ROOT / "site.config.json"

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus"}

DEFAULT_CONFIG = {
    "title": "The Show",
    "tagline": "Every episode, fully transcribed and searchable.",
    "podcast_url": "",
    "feed_url": "",
    "whisper_model": "~/whisper-models/ggml-medium.en.bin",
    "default_speaker": "SPEAKER",
    "speaker_map": "",
    "auto_push": True,
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            sys.exit(f"Could not parse {CONFIG_PATH.name}: {e}")
    return config


def model_path(config: dict) -> Path:
    return Path(config["whisper_model"]).expanduser()


# -------------------- Names and titles --------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "untitled"


def strip_number_prefix(stem: str) -> str:
    """Strips a leading '001-', '12_', '3.', etc. from a filename stem."""
    m = re.match(r"^0*\d+[-_. ]+(.+)$", stem)
    return m.group(1) if m else stem


def guess_episode_title(stem: str):
    """Best-effort parse of '001-my-episode-title' style filenames."""
    m = re.match(r"^0*(\d+)[-_. ]+(.+)$", stem)
    if m:
        return m.group(1), re.sub(r"[-_]+", " ", m.group(2)).strip().title()
    return "?", re.sub(r"[-_]+", " ", stem).strip().title()


def normalize_date(value: str) -> str:
    """Turns an RSS pubDate ('Mon, 15 Jan 2024 08:00:00 +0000') into
    YYYY-MM-DD. Anything that doesn't parse is returned unchanged."""
    value = (value or "").strip()
    if not value or re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return value


def sidecar_path(audio_path: Path) -> Path:
    return audio_path.with_suffix(".json")


def read_sidecar(stem: str) -> dict:
    """fetch_rss_episodes.py saves each episode's real title/date next to its
    audio as audio/<stem>.json. Returns that metadata if present."""
    path = AUDIO_DIR / f"{stem}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


# -------------------- SRT -> transcript --------------------

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


def parse_speaker_map(spec: str) -> dict:
    """'SPEAKER_00=HOST,SPEAKER_01=GUEST' -> {'SPEAKER_00': 'HOST', ...}"""
    name_map = {}
    for pair in (spec or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            name_map[k.strip()] = v.strip()
    return name_map


def render_transcript(entries, speakers, episode, title, date="", guests="none") -> str:
    """Builds the .md file contents. `speakers` is one label per entry."""
    lines = [
        f"[{format_timestamp(start)}] {speaker}: {text}"
        for (start, _end, text), speaker in zip(entries, speakers)
    ]
    duration = format_timestamp(entries[-1][1]) if entries else ""
    # Frontmatter is one line per key, so collapse any stray newlines.
    title = " ".join(str(title).split())
    frontmatter = (
        "---\n"
        f"episode: {episode}\n"
        f"title: {title}\n"
        f"date: {normalize_date(date)}\n"
        f"guests: {guests}\n"
        f"duration: {duration}\n"
        "---\n\n"
    )
    return frontmatter + "\n".join(lines) + "\n"


# -------------------- Auto-publish --------------------

def _git(*args, check=True):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, capture_output=True, text=True
    )


def git_publish(paths, message: str) -> bool:
    """Commits just `paths` and pushes, so GitHub Actions rebuilds the site.

    Only the given files are committed -- anything else you have staged or
    modified is left alone. If the push fails (offline, no remote, etc.) the
    commit stays local and goes up with the next successful push."""
    if not (ROOT / ".git").exists():
        print("  [publish] Not a git repository -- skipping auto-push.", file=sys.stderr)
        return False

    rel = [str(Path(p).resolve().relative_to(ROOT)) for p in paths]
    try:
        _git("add", "--", *rel)
        if _git("diff", "--cached", "--quiet", "--", *rel, check=False).returncode == 0:
            return True  # nothing new to commit
        _git("commit", "-m", message, "--", *rel)
    except subprocess.CalledProcessError as e:
        print(f"  [publish] Commit failed: {e.stderr.strip()}", file=sys.stderr)
        return False

    for attempt in (1, 2):
        try:
            _git("pull", "--rebase", "--autostash")
            _git("push")
            print("  [publish] Pushed -- GitHub Pages will update in a minute or two.")
            return True
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip()
    print(
        f"  [publish] Push failed (commit kept locally, will retry next episode): {err}",
        file=sys.stderr,
    )
    return False
