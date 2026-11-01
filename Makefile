# Shortcuts for the common tasks. Run `make help` to list them.
# Plain `python3 scripts/...` commands work too -- see README.md.

MODEL ?= medium.en
MODEL_DIR ?= $(HOME)/whisper-models
# Diarization needs torch, which lags behind the newest Python releases,
# so the venv prefers an older interpreter when one is installed.
VENV_PYTHON ?= $(shell command -v python3.12 || command -v python3.11 || command -v python3)
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: help setup model diarization transcribe bulk fetch progress site serve

help:
	@echo "make setup        install whisper-cpp + ffmpeg (Homebrew) and download the model"
	@echo "make diarization  (optional) create .venv with pyannote for speaker labels"
	@echo "make transcribe   transcribe new episodes from feed_url, pushing each one"
	@echo "make fetch        download feed audio into audio/ without transcribing"
	@echo "make bulk         transcribe everything in audio/, pushing each one"
	@echo "make progress     show what's transcribed and what's pending"
	@echo "make site         build the site locally into public/"
	@echo "make serve        build and preview at http://localhost:8000"

setup: model
	brew install whisper-cpp ffmpeg

model:
	@mkdir -p "$(MODEL_DIR)"
	@test -f "$(MODEL_DIR)/ggml-$(MODEL).bin" || curl -L --fail -o "$(MODEL_DIR)/ggml-$(MODEL).bin" \
	  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$(MODEL).bin?download=true"
	@echo "Model ready: $(MODEL_DIR)/ggml-$(MODEL).bin"

diarization:
	$(VENV_PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements.txt

transcribe:
	$(PY) scripts/stream_transcribe.py $(ARGS)

fetch:
	python3 scripts/fetch_rss_episodes.py $(ARGS)

bulk:
	$(PY) scripts/bulk_transcribe.py $(ARGS)

progress:
	python3 scripts/check_progress.py

site:
	python3 scripts/build_site.py
	npx --yes pagefind@1.3.0 --site public

serve: site
	python3 -m http.server -d public 8000
