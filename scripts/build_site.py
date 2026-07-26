#!/usr/bin/env python3
"""
Builds the static site from Markdown transcripts.

Reads every .md file in /transcripts, parses a small YAML-ish frontmatter
block, converts the transcript body into HTML, and writes:

  public/index.html              -- the ledger/homepage with search box
  public/episodes/<slug>.html    -- one page per episode
  public/episodes.json           -- lightweight index used by the homepage

Run:  python3 scripts/build_site.py
"""
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = ROOT / "transcripts"
PUBLIC_DIR = ROOT / "public"
ASSETS_DIR = ROOT / "assets"
TEMPLATES_DIR = ROOT / "scripts" / "templates"


def parse_frontmatter(text: str):
    """Splits a leading --- frontmatter block from the body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError("Transcript is missing a --- frontmatter block")
    fm_raw, body = match.groups()
    meta = {}
    for line in fm_raw.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body.strip()


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


def transcript_to_html(body: str) -> str:
    """Turns [MM:SS] SPEAKER: line blocks into tagged HTML paragraphs."""
    line_pattern = re.compile(r"^\[(?P<ts>[\d:]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$")
    paragraphs = []
    for raw_line in body.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        m = line_pattern.match(raw_line)
        if m:
            ts = html.escape(m.group("ts"))
            speaker = html.escape(m.group("speaker").strip())
            text = html.escape(m.group("text").strip())
            paragraphs.append(
                f'<p class="line"><span class="ts">{ts}</span>'
                f'<span class="speaker">{speaker}</span>'
                f'<span class="text">{text}</span></p>'
            )
        else:
            paragraphs.append(f'<p class="line plain">{html.escape(raw_line)}</p>')
    return "\n".join(paragraphs)


def load_episodes():
    episodes = []
    for path in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        title = meta.get("title", path.stem)
        slug = slugify(f"{meta.get('episode', '0')}-{title}")
        episodes.append({
            "episode": meta.get("episode", "?"),
            "title": title,
            "date": meta.get("date", ""),
            "guests": meta.get("guests", "none"),
            "duration": meta.get("duration", ""),
            "slug": slug,
            "body_html": transcript_to_html(body),
            "body_text": re.sub(r"\s+", " ", body),
        })
    episodes.sort(key=lambda e: int(e["episode"]) if str(e["episode"]).isdigit() else 0)
    return episodes


EPISODE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ep. {episode} — {title}</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="wrap">
  <a class="back" href="../index.html">&larr; All episodes</a>
  <header class="ep-header">
    <div class="ep-number">{episode:0>3}</div>
    <div class="ep-meta">
      <h1>{title}</h1>
      <p class="meta-line">{date} &middot; {duration}{guest_line}</p>
    </div>
  </header>
  <div class="waveform-rule" aria-hidden="true"></div>
  <main class="transcript" data-pagefind-body>
    {body}
  </main>
</div>
</body>
</html>
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{site_title} — Transcript Archive</title>
<link rel="stylesheet" href="assets/style.css">
<link rel="stylesheet" href="pagefind/pagefind-ui.css">
</head>
<body>
<div class="wrap">
  <header class="hero">
    <p class="eyebrow">Transcript Archive</p>
    <h1>{site_title}</h1>
    <p class="hero-sub">Every episode, fully transcribed and searchable. {count} episodes and counting.</p>
    <div id="search"></div>
  </header>
  <div class="waveform-rule" aria-hidden="true"></div>
  <main>
    <ul class="ledger">
      {rows}
    </ul>
  </main>
</div>
<script src="pagefind/pagefind-ui.js"></script>
<script>
  window.addEventListener('DOMContentLoaded', () => {{
    new PagefindUI({{ element: "#search", showSubResults: true, showImages: false }});
  }});
</script>
</body>
</html>
"""

ROW_TEMPLATE = """<li class="ledger-row">
  <a href="episodes/{slug}.html">
    <span class="ep-number">{episode:0>3}</span>
    <span class="ledger-title">{title}</span>
    <span class="ledger-date">{date}</span>
  </a>
</li>"""


def build():
    if PUBLIC_DIR.exists():
        shutil.rmtree(PUBLIC_DIR)
    (PUBLIC_DIR / "episodes").mkdir(parents=True)
    shutil.copytree(ASSETS_DIR, PUBLIC_DIR / "assets")

    episodes = load_episodes()
    if not episodes:
        print("No transcripts found in /transcripts — add some .md files first.")

    for ep in episodes:
        guest_line = f" &middot; with {ep['guests']}" if ep["guests"] and ep["guests"].lower() != "none" else ""
        html_out = EPISODE_TEMPLATE.format(
            episode=int(ep["episode"]) if str(ep["episode"]).isdigit() else ep["episode"],
            title=html.escape(ep["title"]),
            date=html.escape(ep["date"]),
            duration=html.escape(ep["duration"]),
            guest_line=guest_line,
            body=ep["body_html"],
        )
        (PUBLIC_DIR / "episodes" / f"{ep['slug']}.html").write_text(html_out, encoding="utf-8")

    rows = "\n".join(
        ROW_TEMPLATE.format(
            slug=ep["slug"],
            episode=int(ep["episode"]) if str(ep["episode"]).isdigit() else ep["episode"],
            title=html.escape(ep["title"]),
            date=html.escape(ep["date"]),
        )
        for ep in reversed(episodes)
    )

    index_html = INDEX_TEMPLATE.format(
        site_title="The Show",
        count=len(episodes),
        rows=rows,
    )
    (PUBLIC_DIR / "index.html").write_text(index_html, encoding="utf-8")

    # Lightweight JSON index too, in case you want to build your own UI later.
    (PUBLIC_DIR / "episodes.json").write_text(
        json.dumps([{k: v for k, v in ep.items() if k != "body_html"} for ep in episodes], indent=2),
        encoding="utf-8",
    )

    print(f"Built {len(episodes)} episode page(s) into {PUBLIC_DIR}")


if __name__ == "__main__":
    build()
