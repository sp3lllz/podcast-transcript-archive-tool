# Podcast Transcript Archive

A static, fuzzy-searchable archive of podcast transcripts, built for GitHub
Pages. No backend, no database just Markdown files in, a searchable
website out.

> **Run every command in this README from the project's root folder** (the
> folder this README is in). All scripts use paths like `audio/` and
> `transcripts/` relative to wherever you run them from, so this works the
> same on any machine regardless of where you put the project or what your
> username is -- there's nothing machine-specific to edit.

## How it works

- Every episode is a Markdown file in `/transcripts`, one file per episode.
- `scripts/build_site.py` reads those files and generates a static site into
  `/public`: a homepage ("ledger") listing every episode, and one page per
  episode with the full transcript.
- [Pagefind](https://pagefind.app) indexes the generated `/public` folder and
  gives you fast, typo-tolerant (fuzzy) full-text search across every
  transcript, without shipping all the text to the browser up front. This
  scales comfortably to hundreds of episodes it only pulls in what a
  search actually needs.
- A GitHub Actions workflow (`.github/workflows/deploy.yml`) runs the build
  and Pagefind indexing automatically on every push to `main`, and deploys
  the result to GitHub Pages.

## Adding your transcripts

Create one `.md` file per episode in `/transcripts`. Format:

```markdown
---
episode: 4
title: Your Episode Title
date: 2024-02-01
guests: Jane Doe
duration: 45:10
---

[00:00] HOST: Line of dialogue here.
[00:32] GUEST: Reply here.
```

Notes:
- `guests: none` if there's no guest it'll be hidden on the episode page.
- The `[MM:SS] SPEAKER: text` format is optional per line any line that
  doesn't match it is rendered as plain text (useful for intros, show notes,
  or ad breaks pasted into the transcript).
- Filenames don't matter for display (the `episode` number and `title` in
  the frontmatter control that) but naming them `001-title.md`,
  `002-title.md` etc. keeps the folder easy to scan.
- 3 sample episodes are included so you can see the format and preview the
  site immediately delete them once you've added your own.

## Streaming straight from the feed (low disk footprint)

If you'd rather not keep a full local audio archive, `stream_transcribe.py`
does the whole pipeline directly from the RSS feed, one episode at a time:
download → transcribe → diarize → write the `.md` → delete the audio →
move to the next episode. At most one episode's audio ever sits on disk.

```bash
source ~/whisper-env/bin/activate
export HF_TOKEN=hf_xxxxxxxx
python3 scripts/stream_transcribe.py "https://example.com/feed.xml"
```

It uses the same duplicate-detection as `fetch_rss_episodes.py` (title
matching against both the audio and transcript folders), so it's safe to
run repeatedly as new episodes get published -- it'll only process what's
actually new.

Useful options:
- `--dry-run` list what would be processed without downloading or
  transcribing anything. Worth running once first, same as with
  `fetch_rss_episodes.py`.
- `--limit 5` only process 5 pending episodes this run, then stop (handy
  for testing, or for deliberately working through a big backlog in
  smaller sessions).
- `--keep-audio` keep the downloaded audio instead of deleting it after
  transcribing, if you change your mind about wanting a local archive.
- `--speaker-map "SPEAKER_00=HOST,SPEAKER_01=GUEST"` same as the batch
  script, rename diarization labels once you know who's who.
- `--model`, `--audio-dir`, `--transcript-dir` override any default path.

If an episode fails partway through (a bad download, a transcription
error, etc), its audio is kept on disk for debugging rather than silently
deleted, and the script moves on to the next episode rather than stopping
the whole run.

**When to use this vs. the other scripts:** this is the simplest path if
you're pulling everything from the feed and don't need the raw audio kept
around afterward. Use `fetch_rss_episodes.py` + `bulk_transcribe.sh`
instead if you want to keep a local audio archive, inspect/curate the
downloaded files before transcribing, or already have audio from other
sources mixed in.

## Pulling audio from the podcast's RSS feed

Instead of manually placing files in the audio folder, `fetch_rss_episodes.py`
downloads episode audio directly from the podcast's RSS feed:

```bash
python3 scripts/fetch_rss_episodes.py "https://example.com/feed.xml"
```

- Numbers files to match the pipeline's convention (`001-episode-title.mp3`,
  `002-...`), using the feed's episode titles.
- Reverses the feed's order so episode `001` is the oldest/first-released
  episode, not the most recent (RSS feeds list newest first by convention --
  pass `--newest-first` to keep that order instead).
- Uses only Python's standard library, no extra installs required.

**Duplicate detection:** it checks episode titles (not exact filenames)
against BOTH the audio folder and the transcripts folder before downloading
anything, so it correctly recognizes an episode you already have even if:
- it was downloaded/named manually before this script existed, or
- the transcript exists but the original audio file is gone (renamed,
  moved, cleaned up, etc) -- a transcript alone counts as "already have it."

Matching is fuzzy (exact, substring, and close-enough similarity), so minor
differences in punctuation or numbering between the feed's title and your
existing filenames won't cause a re-download. If you want to double check
what it will do before it downloads anything:

```bash
python3 scripts/fetch_rss_episodes.py "https://example.com/feed.xml" --dry-run
```

This prints exactly what would be skipped (and why) and what would be
downloaded, without touching any files. Worth running once after a feed or
folder change to sanity-check the matching before a real run.

Other options:
- `--transcript-dir PATH` / `--audio-dir PATH` if either folder isn't at the
  default location.
- `--match-threshold 0.9` to make fuzzy matching stricter (fewer false
  "already have it" positives, but more risk of re-downloading something you
  do already have); lower it to be more lenient.

Run this first, then run `bulk_transcribe.sh` as normal against the audio
it downloads.

## Checking transcription progress

`bulk_transcribe.sh` already skips any episode that already has a `.md` file
in the transcripts folder, so pausing partway through a batch (Ctrl+C) and
running it again later resumes automatically -- nothing extra is needed for
that. To see exactly where things stand without kicking off a new batch run:

```bash
python3 scripts/check_progress.py
```

This lists the total number of audio files found, how many already have a
transcript, and the filenames of whatever's still pending.

## Bulk transcribing audio (macOS)

If you have raw audio and need transcripts, `scripts/bulk_transcribe.sh` runs
[whisper-cpp](https://github.com/ggml-org/whisper.cpp) over a folder of audio
files and writes out `.md` files already in this site's format.

**One-time setup:**

```bash
brew install whisper-cpp ffmpeg
mkdir -p ~/whisper-models
curl -L -o ~/whisper-models/ggml-medium.en.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin?download=true"
```

`medium.en` is a good accuracy/speed balance for English podcasts. Swap in
`ggml-small.en.bin` for a faster/rougher pass, or `ggml-large-v3.bin` for the
best quality (slower, ~3GB download).

**Run it:**

```bash
chmod +x scripts/bulk_transcribe.sh
./scripts/bulk_transcribe.sh
```

The script is preconfigured to read audio from `audio/` and write
transcripts to `transcripts/`, both relative to the project root -- run it
from the project's root folder (e.g. `./scripts/bulk_transcribe.sh`). It:

- Skips any episode that already has a `.md` file in the Transcripts folder,
  so you can stop and resume freely across a multi-day batch job.
- Converts each audio file to 16kHz mono WAV (what whisper-cpp expects),
  transcribes it, and converts the result into `[MM:SS] SPEAKER: text` lines
  with frontmatter guessed from the filename (`001-episode-title.mp3` →
  episode 1, title "Episode Title").

**Speaker labels via pyannote (local diarization):** the pipeline now
identifies who's speaking, fully offline, using
[pyannote.audio](https://github.com/pyannote/pyannote-audio). Unlike simple
turn-detection, it clusters voices across the whole episode, so the same
person gets the same label even if they speak again 20 minutes later.

One-time setup:

```bash
pip3 install pyannote.audio --break-system-packages
```

Then:
1. Create a free Hugging Face account: https://huggingface.co/join
2. Visit and accept the terms on both of these model pages (just click
   "Agree" while logged in no download needed):
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Create a read-access token: https://huggingface.co/settings/tokens
4. `export HF_TOKEN=hf_xxxxxxxx` in your shell (or add it to your shell
   profile so it persists)

Then run the batch script as before:

```bash
export HF_TOKEN=hf_xxxxxxxx
./scripts/bulk_transcribe.sh
```

Diarization is slower than transcription on CPU, so budget extra time per
episode. Speakers come out labeled `SPEAKER_00`, `SPEAKER_01`, etc you
won't know which number is which person until you check a transcript. Once
you do, set `SPEAKER_MAP` to rename them for the rest of the batch:

```bash
export SPEAKER_MAP="SPEAKER_00=HOST,SPEAKER_01=GUEST"
./scripts/bulk_transcribe.sh
```

(Since a fresh guest each episode may not always map to the same
`SPEAKER_NN`, spot-check a few files after a batch run and rename in the
`.md` files directly if needed they're plain text.)

After transcribing, double-check the frontmatter (especially `date` and
`guests`, which the script can't infer) and spot-check a few transcripts —
Whisper models occasionally hallucinate text over silence or music, and
diarization can misattribute short overlapping lines.

## Running locally

```bash
python3 scripts/build_site.py
npx pagefind --site public
python3 -m http.server -d public 8000
```

Then open `http://localhost:8000`.

(The first two commands need Python 3 and Node.js. Pagefind's CLI is fetched
on demand by `npx`, no separate install required.)

## Deploying to GitHub Pages

1. Push this repo to GitHub.
2. In the repo settings, go to **Pages** and set the source to
   **GitHub Actions**.
3. Push to `main` (or run the workflow manually from the Actions tab). The
   workflow builds the site, runs Pagefind, and publishes to Pages
   automatically.

## Project structure

```
transcripts/            your source .md transcripts (one per episode)
scripts/build_site.py    generates the static site
assets/style.css         site design
public/                  generated output (git-ignored; rebuilt each run)
.github/workflows/       CI that builds + deploys on push
```

## Customizing

- **Site title**: edit `site_title="The Show"` in `scripts/build_site.py`.
- **Design**: everything lives in `assets/style.css` as CSS custom
  properties at the top of the file (colors, fonts) change those and the
  whole site follows.
- **Search behavior**: Pagefind options are set in the `<script>` block at
  the bottom of the generated `index.html` template inside
  `scripts/build_site.py` (search `PagefindUI(`). See the
  [Pagefind docs](https://pagefind.app/docs/ui/) for all options (filters,
  sorting, result excerpt length, etc.).
