# Podcast Transcript Archive

Turn a podcast's RSS feed into a searchable transcript website on GitHub
Pages. Transcription runs locally on your machine with
[whisper.cpp](https://github.com/ggml-org/whisper.cpp); every time an episode
finishes it's committed and pushed, and GitHub Actions rebuilds the site --
so the archive fills in live while a backlog is being transcribed.

No backend, no database: Markdown files in, a static searchable site out.

## Quick start

### 1. Create your own copy and switch on GitHub Pages

1. Click **Use this template → Create a new repository** at the top of this
   page. Give it a name (e.g. `my-podcast-transcripts`); it can be public or
   private (private Pages sites need a paid GitHub plan).
2. In your new repository, go to **Settings → Pages** and set **Source** to
   **GitHub Actions**.

The first "Build and deploy site" run in your new repository may fail
because Pages wasn't switched on yet. That's expected: the next push
deploys normally.

Using the GitHub CLI instead? This does step 1 and clones it in one go:

```bash
gh repo create my-podcast-transcripts --template sp3lllz/podcast-transcript-archive-tool --public --clone
```

### 2. Clone it and point it at your podcast

Skip the clone if you used the `gh` command above.

```bash
git clone git@github.com:YOUR-USERNAME/YOUR-REPO.git
cd YOUR-REPO
```

Edit `site.config.json`:

```json
{
  "title": "My Podcast",
  "tagline": "Every episode, fully transcribed and searchable.",
  "podcast_url": "https://my-podcast.example.com",
  "feed_url": "https://my-podcast.example.com/feed.xml",
  "whisper_model": "~/whisper-models/ggml-medium.en.bin",
  "default_speaker": "SPEAKER",
  "speaker_map": "",
  "auto_push": true
}
```

| Key | What it does |
| --- | --- |
| `title`, `tagline` | Shown on the site's homepage. |
| `podcast_url` | Optional "Listen to the show" link on the homepage. |
| `feed_url` | The podcast's RSS feed. Scripts use it when you don't pass a URL. |
| `whisper_model` | Path to the whisper.cpp model file. |
| `default_speaker` | Speaker label used when diarization is off (e.g. `HOST` for a solo show). |
| `speaker_map` | Renames diarization labels, e.g. `SPEAKER_00=ALEX,SPEAKER_01=SAM`. |
| `auto_push` | Commit and push each transcript as soon as it's written. |

Then commit and push your config:

```bash
git commit -am "Configure archive for my podcast"
git push
```

### 3. Install the transcription tools (macOS, once)

```bash
make setup
```

This runs `brew install whisper-cpp ffmpeg` and downloads the
`medium.en` model (~1.5 GB) to `~/whisper-models/`. Use a different model
with e.g. `make model MODEL=small.en` (faster, rougher) or
`MODEL=large-v3` (best quality, ~3 GB, slower; also handles non-English) --
then update `whisper_model` in `site.config.json` to match.

On Linux, install whisper.cpp and ffmpeg (Homebrew on Linux works, or build
whisper.cpp from source) and then run `make model`.

### 4. Transcribe

```bash
make transcribe
```

For each episode in the feed that isn't in the archive yet, this downloads
the audio, transcribes it, writes `transcripts/NNN-episode-title.md`,
**commits and pushes it**, deletes the audio, and moves on. Your site at
`https://YOUR-USERNAME.github.io/YOUR-REPO/` updates a
minute or two after each push.

- Episode `001` is the oldest episode; titles and release dates come from
  the feed.
- Stop any time with Ctrl+C and re-run to resume -- finished episodes are
  skipped, and a half-done episode is simply redone.
- Run it again whenever new episodes come out; it only processes new ones.
- Big backlog? Keep your Mac awake with `caffeinate -i make transcribe`.
- Pass options through `ARGS`, e.g. `make transcribe ARGS="--limit 5"` or
  `ARGS="--dry-run"` to just list what would be processed.

> **Pushing needs working git credentials.** Clone over SSH, or sign in with
> `gh auth login`, so `git push` works without a password prompt. If a push
> fails (offline, etc.), the commit is kept locally and goes up with the next
> episode's push.

Prefer to push yourself? Set `"auto_push": false` (or pass
`ARGS="--no-push"`) and `git push` whenever you like.

## Speaker labels (optional)

By default every line is labelled with `default_speaker`. To identify who's
speaking, enable [pyannote](https://github.com/pyannote/pyannote-audio)
diarization, which runs fully offline after a one-time model download:

1. `make diarization` -- creates `.venv/` and installs pyannote (a large
   download, since it includes PyTorch). The `make` commands use `.venv`
   automatically once it exists.
2. Create a free [Hugging Face account](https://huggingface.co/join) and
   click **Agree** on both
   [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   and [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0).
3. Create a read token at https://huggingface.co/settings/tokens and
   `export HF_TOKEN=hf_xxxxxxxx` (add it to your shell profile to keep it).

Speakers come out as `SPEAKER_00`, `SPEAKER_01`, ... Check a transcript, then
set `speaker_map` in `site.config.json` (e.g. `SPEAKER_00=HOST,SPEAKER_01=GUEST`)
for the rest of the run. Labels can shift between episodes, especially with
different guests, so spot-check a few -- transcripts are plain text and easy
to fix by hand. Diarization is slower than transcription; it uses the Apple
GPU (or CUDA) when available.

## Keeping a local audio archive instead

If you want the audio kept, or have audio from somewhere other than the
feed:

```bash
make fetch        # download feed audio into audio/ (with title/date metadata)
make progress     # see what's transcribed and what's pending
make bulk         # transcribe everything in audio/, pushing each transcript
```

Audio files you add by hand should be named `001-episode-title.mp3` so the
episode number and title can be guessed (fix up `date`/`guests` in the
`.md` afterwards). `audio/` is git-ignored, so audio never gets committed.

`make fetch` matches feed titles against both `audio/` and `transcripts/`
(fuzzy: exact, substring or close similarity), so episodes you already have
aren't re-downloaded. Use `ARGS="--dry-run"` to check its decisions first,
or `--match-threshold 0.9` to make matching stricter.

## Transcript format

One `.md` file per episode in `transcripts/`:

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

- `guests: none` hides the guest line on the episode page.
- Lines that don't match `[MM:SS] SPEAKER: text` are shown as plain notes
  (handy for show notes or ad-break markers).
- Every timestamp on the site is a link to that moment
  (`.../episode.html#t-10-40`), so you can share a quote.
- Review transcripts now and then: Whisper occasionally hallucinates text
  over music or silence. Edit, commit and push -- the site rebuilds.

## Previewing the site locally

```bash
make serve
```

Builds into `public/`, indexes it with [Pagefind](https://pagefind.app), and
serves it at http://localhost:8000. Needs Python 3 and Node.js (`npx` fetches
Pagefind on demand). Search matches whole words and word prefixes across
every transcript, and only downloads the parts of the index a search needs,
so it stays fast with hundreds of episodes.

## How the site is built

`.github/workflows/deploy.yml` runs on every push to `main`:
`scripts/build_site.py` turns the transcripts into HTML, Pagefind indexes
them, and the result is deployed to GitHub Pages. Rapid pushes cancel
older in-progress builds, so only the latest state is deployed.

## Project structure

```
site.config.json                 your podcast's settings
transcripts/                     one .md per episode (committed)
audio/                           downloaded audio (git-ignored)
assets/style.css                 site design (colors/fonts at the top)
scripts/stream_transcribe.py     feed -> transcript -> push, one episode at a time
scripts/fetch_rss_episodes.py    download feed audio into audio/
scripts/bulk_transcribe.py       transcribe everything in audio/
scripts/check_progress.py        what's done / pending
scripts/diarize_and_transcribe.py  turn one .srt + .wav into a transcript
scripts/build_site.py            generate the static site into public/
.github/workflows/deploy.yml     build + deploy on push
```

All scripts resolve paths from the project root, so you can run them from
any folder. Without `make`, use the scripts directly, e.g.
`python3 scripts/stream_transcribe.py --help`.

## Getting updates to the tool

Repositories made from a template don't receive later changes
automatically. To pull in improvements to the scripts, site design or
workflow, run this once in your repository:

```bash
git remote add upstream https://github.com/sp3lllz/podcast-transcript-archive-tool.git
```

Then, whenever you want the latest version:

```bash
git fetch upstream
git merge upstream/main --allow-unrelated-histories
```

`--allow-unrelated-histories` is only needed the first time. If
`site.config.json` or `assets/style.css` conflict, keep your own version;
your transcripts are never touched.

## Customizing

- **Design**: edit the CSS custom properties at the top of
  `assets/style.css` -- the whole site follows.
- **Search**: Pagefind UI options live in the `PagefindUI(` call in
  `scripts/build_site.py`. See the [Pagefind docs](https://pagefind.app/docs/ui/).
