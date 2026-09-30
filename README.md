# Almanac

A local personal assistant that turns syllabi, documents and chat into goals, projects, tasks and a calendar, then helps you keep up with them. All AI runs on your own PC through [Ollama](https://ollama.com); nothing is sent to a cloud model.

Every change the assistant wants to make arrives as a proposal with the quote it came from. Anything the source doesn't state (a date, a time, which paper you present) is asked, never guessed.

Design: [`.scratch/almanac-v1/spec.md`](.scratch/almanac-v1/spec.md) · vocabulary: [`CONTEXT.md`](CONTEXT.md) · work tickets: [`.scratch/almanac-v1/issues/`](.scratch/almanac-v1/issues/)

## Run

Requires Python 3.12 and Ollama with `qwen3.5:9b-q8_0` pulled.

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8001
```

Open http://127.0.0.1:8001. Data lives in `data/almanac.db` (set `ALMANAC_DB` to move it).

## Test

```
.venv\Scripts\python -m pytest
```

The extraction eval runs the real model over syllabi in `seed/` (kept local, not committed) and scores it against the hand labels in `seed/expected.json`:

```
.venv\Scripts\python scripts\eval.py [--model qwen3.5:35b-a3b] [--verbose]
```
