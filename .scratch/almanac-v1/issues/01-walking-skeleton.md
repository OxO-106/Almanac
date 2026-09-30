# 01: Walking skeleton

**What to build:** Almanac starts as its own FastAPI server on 127.0.0.1:8001 with an empty SQLite store and serves a Today page that shows whether the assistant is ready (Ollama running, model present) and a plain message when it isn't. The test harness exists: the app can be driven in-process with a scripted fake LLM and a controllable clock.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Server starts from a single command and serves the Today page
- [x] Health endpoint reports model name and readiness; Today shows 'Ollama is not running' / 'model missing' states
- [x] LLM client uses the same model and 32k context size as Papercut, configurable in settings
- [x] pytest suite drives the app over HTTP with a scripted LLM and a settable clock; one passing test per behaviour above
