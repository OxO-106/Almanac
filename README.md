# Almanac

A local personal assistant that turns syllabi, documents and chat into goals, projects, tasks and a calendar, then helps you keep up with them. All AI runs on your own PC through [Ollama](https://ollama.com); nothing is sent to a cloud model.

Every change the assistant wants to make arrives as a proposal with the quote it came from. Anything the source doesn't state (a date, a time, which paper you present) is asked, never guessed.

Design: [`.scratch/almanac-v1/spec.md`](.scratch/almanac-v1/spec.md) · vocabulary: [`CONTEXT.md`](CONTEXT.md) · work tickets: [`.scratch/almanac-v1/issues/`](.scratch/almanac-v1/issues/)

## Run

**Start menu → Almanac.** It starts Ollama, the Almanac server (this PC only, port 8001, log in `almanac.log`), the tray icon and Tailscale Serve, then opens Almanac in an Edge app window. `stop-almanac.bat` or the tray icon stops it. Run `start-almanac.ps1` from a console to see each step.

**Tray icon:** coloured while the server runs, grey when stopped. Almanac's notifications (9am briefing, 8pm/11pm check-ins, timer, overviews) pop up from it as Windows notifications. Right-click to copy the laptop link.

**Laptop:** https://&lt;this PC&gt;.&lt;tailnet&gt;.ts.net:8443 over [Tailscale](https://tailscale.com), reachable only by your own devices (Papercut keeps the default port). `tailscale serve --https=8443 off` stops sharing it.

**Models:** chat uses `qwen3.5:9b-q8_0` (shared with Papercut); reading documents uses `qwen3.5:35b-a3b` if it is pulled, else the 9B. Both run through Ollama on this PC.

## Setup from scratch

Requires Python 3.12, Ollama with the models above, and (for the laptop) Tailscale.

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\install-start-menu.ps1
```

Data lives in `data/almanac.db` (set `ALMANAC_DB` to move it), backed up nightly at 10:45pm to `data/backups/` (last 14 kept).

## Test

```
.venv\Scripts\python -m pytest
```

The extraction eval runs the real model over syllabi in `seed/` (kept local, not committed) and scores it against the hand labels in `seed/expected.json`:

```
.venv\Scripts\python scripts\eval.py [--model qwen3.5:35b-a3b] [--verbose]
```
