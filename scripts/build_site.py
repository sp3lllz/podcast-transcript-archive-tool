#!/usr/bin/env python3
"""
Builds the static site from Markdown transcripts.

Reads every .md file in /transcripts, parses a small YAML-ish frontmatter
block, converts the transcript body into HTML, and writes:

  public/index.html              -- the ledger/homepage with search box
  public/episodes/<slug>.html    -- one page per episode
  public/episodes.json           -- lightweight index for custom UIs

Site title, tagline and podcast link come from site.config.json.

Run:  python3 scripts/build_site.py
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, TRANSCRIPT_DIR, load_config, slugify  # noqa: E402

PUBLIC_DIR = ROOT / "public"
ASSETS_DIR = ROOT / "assets"

FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Archivo:wdth,wght@100..125,400..700&family=IBM+Plex+Mono:wght@400&'
    'family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">'
)


def parse_frontmatter(text: str):
    """Splits a leading --- frontmatter block from the body."""
    match = re.match(r"^﻿?---\s*\n(.*?)\n---\s*(?:\n(.*))?$", text, re.DOTALL)
    if not match:
        raise ValueError("missing the --- frontmatter block at the top of the file")
    fm_raw, body = match.groups()
    meta = {}
    for line in fm_raw.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, (body or "").strip()


def ts_anchor(ts: str) -> str:
    return "t-" + ts.replace(":", "-")


def transcript_to_html(body: str) -> str:
    """Turns [MM:SS] SPEAKER: line blocks into tagged HTML paragraphs. Each
    timestamp is a link to its own line, so you can share a moment."""
    line_pattern = re.compile(r"^\[(?P<ts>[\d:]+)\]\s*(?P<speaker>[^:\]]{1,40}):\s*(?P<text>.*)$")
    paragraphs, seen = [], set()
    for raw_line in body.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        m = line_pattern.match(raw_line)
        if m:
            ts = html.escape(m.group("ts"))
            anchor = ts_anchor(ts)
            id_attr = "" if anchor in seen else f' id="{anchor}"'
            seen.add(anchor)
            speaker = html.escape(m.group("speaker").strip())
            text = html.escape(m.group("text").strip())
            paragraphs.append(
                f'<p class="line"{id_attr}><a class="ts" href="#{anchor}">{ts}</a>'
                f'<span class="speaker">{speaker}</span>'
                f'<span class="text">{text}</span></p>'
            )
        else:
            paragraphs.append(f'<p class="line plain">{html.escape(raw_line)}</p>')
    return "\n".join(paragraphs)


def episode_sort_key(ep):
    n = str(ep["episode"])
    return (0, int(n), ep["title"]) if n.isdigit() else (1, 0, ep["title"])


def load_episodes():
    episodes, errors, slugs = [], [], {}
    for path in sorted(TRANSCRIPT_DIR.glob("*.md")):
        try:
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            errors.append(f"{path.name}: {e}")
            continue
        title = meta.get("title") or path.stem
        episode = meta.get("episode") or "?"
        slug = slugify(f"{episode}-{title}")
        if slug in slugs:
            slug = slugify(path.stem)
        slugs[slug] = path.name
        episodes.append({
            "episode": episode,
            "title": title,
            "date": meta.get("date", ""),
            "guests": meta.get("guests", "none"),
            "duration": meta.get("duration", ""),
            "slug": slug,
            "body_html": transcript_to_html(body),
        })
    if errors:
        sys.exit("Could not build -- fix these transcript files:\n  " + "\n  ".join(errors))
    episodes.sort(key=episode_sort_key)
    return episodes


def ep_number(ep):
    n = str(ep["episode"])
    return f"{int(n):03d}" if n.isdigit() else html.escape(n)


EPISODE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ep. {number} — {title} · {site_title}</title>
<meta name="description" content="Full transcript of {site_title} episode {number}: {title}">
{fonts}
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="wrap">
  <a class="back" href="../index.html">&larr; All episodes</a>
  <header class="ep-header">
    <div class="ep-number">{number}</div>
    <div class="ep-meta">
      <h1 data-pagefind-meta="title">{title}</h1>
      <p class="meta-line">{meta_line}</p>
    </div>
  </header>
  <div class="waveform-rule" aria-hidden="true"></div>
  <main class="transcript" data-pagefind-body>
    {body}
  </main>
  <nav class="ep-nav">{prev_link}{next_link}</nav>
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
<meta name="description" content="{tagline}">
{fonts}
<link rel="stylesheet" href="assets/style.css">
<link rel="stylesheet" href="pagefind/pagefind-ui.css">
</head>
<body>
<div class="wrap">
  <header class="hero">
    <p class="eyebrow">Transcript Archive</p>
    <h1>{site_title}</h1>
    <p class="hero-sub">{tagline} {count} episode{plural} and counting.{podcast_link}</p>
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
    if (typeof PagefindUI === 'undefined') return; // not indexed yet (local build without pagefind)
    new PagefindUI({{ element: "#search", showSubResults: true, showImages: false }});
  }});
</script>
</body>
</html>
"""

ROW_TEMPLATE = """<li class="ledger-row">
  <a href="episodes/{slug}.html">
    <span class="ep-number">{number}</span>
    <span class="ledger-title">{title}</span>
    <span class="ledger-date">{date}</span>
  </a>
</li>"""


def build():
    config = load_config()
    site_title = html.escape(config["title"])

    if PUBLIC_DIR.exists():
        shutil.rmtree(PUBLIC_DIR)
    (PUBLIC_DIR / "episodes").mkdir(parents=True)
    shutil.copytree(ASSETS_DIR, PUBLIC_DIR / "assets")
    (PUBLIC_DIR / ".nojekyll").touch()  # serve files as-is on GitHub Pages

    episodes = load_episodes()
    if not episodes:
        print("No transcripts found in /transcripts — add some .md files first.")

    for i, ep in enumerate(episodes):
        guests = ep["guests"]
        meta_parts = [ep["date"], ep["duration"]]
        if guests and guests.lower() != "none":
            meta_parts.append(f"with {guests}")
        prev_ep = episodes[i - 1] if i > 0 else None
        next_ep = episodes[i + 1] if i + 1 < len(episodes) else None
        html_out = EPISODE_TEMPLATE.format(
            number=ep_number(ep),
            title=html.escape(ep["title"]),
            site_title=site_title,
            fonts=FONTS_LINK,
            meta_line=" &middot; ".join(html.escape(p) for p in meta_parts if p),
            body=ep["body_html"],
            prev_link=(f'<a class="prev" href="{prev_ep["slug"]}.html">&larr; {html.escape(prev_ep["title"])}</a>'
                       if prev_ep else "<span></span>"),
            next_link=(f'<a class="next" href="{next_ep["slug"]}.html">{html.escape(next_ep["title"])} &rarr;</a>'
                       if next_ep else "<span></span>"),
        )
        (PUBLIC_DIR / "episodes" / f"{ep['slug']}.html").write_text(html_out, encoding="utf-8")

    rows = "\n".join(
        ROW_TEMPLATE.format(
            slug=ep["slug"],
            number=ep_number(ep),
            title=html.escape(ep["title"]),
            date=html.escape(ep["date"]),
        )
        for ep in reversed(episodes)
    )

    podcast_url = config.get("podcast_url", "")
    podcast_link = (f' <a href="{html.escape(podcast_url, quote=True)}">Listen to the show &rarr;</a>'
                    if podcast_url else "")
    index_html = INDEX_TEMPLATE.format(
        site_title=site_title,
        tagline=html.escape(config["tagline"]),
        fonts=FONTS_LINK,
        count=len(episodes),
        plural="" if len(episodes) == 1 else "s",
        podcast_link=podcast_link,
        rows=rows,
    )
    (PUBLIC_DIR / "index.html").write_text(index_html, encoding="utf-8")

    (PUBLIC_DIR / "episodes.json").write_text(
        json.dumps([{k: v for k, v in ep.items() if k != "body_html"} for ep in episodes], indent=2),
        encoding="utf-8",
    )

    print(f"Built {len(episodes)} episode page(s) into {PUBLIC_DIR}")


if __name__ == "__main__":
    build()
