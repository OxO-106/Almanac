"""Local LLM access through Ollama, which Papercut shares: same context size, so
a model loaded by one app serves the other without a reload (a different num_ctx
would make Ollama reload it on every switch)."""

import json
from typing import Callable, Iterator

import httpx

KEEP_ALIVE = "30m"
TIMEOUT = httpx.Timeout(180, connect=10)
NUM_CTX = 32768  # must match Papercut's
# One model for chat and documents: the 35B MoE reads chat far better than the 9B
# (scripts/chat_eval.py: 32/32 vs 26/32) at the same speed once loaded, and finds
# more deadlines in syllabi (scripts/eval.py). One model means Almanac never swaps
# between its own two; Ollama swaps only when Papercut (the 9B) is used.
DEFAULT_MODEL = "qwen3.5:35b-a3b"
DEFAULT_READER = DEFAULT_MODEL
FALLBACK_MODEL = "qwen3.5:9b-q8_0"  # if the 35B isn't downloaded
# 127.0.0.1, not localhost: Windows tries IPv6 first and Ollama listens on IPv4.
DEFAULT_URL = "http://127.0.0.1:11434"


class Ollama:
    """key: the settings entry under "ai" naming the model ("model" for chat,
    "reader_model" for documents). A reader model that isn't downloaded falls
    back to the chat model; a default chat model that isn't, to the 9B."""

    def __init__(self, settings: Callable[[], dict] = dict, key: str = "model", default: str = DEFAULT_MODEL):
        self._settings, self._key, self._default = settings, key, default

    def _cfg(self):
        s = self._settings().get("ai", {})
        url = (s.get("url") or DEFAULT_URL).rstrip("/")
        model = s.get(self._key) or self._default
        if self._key != "model" and not self._installed(url, model):
            model = s.get("model") or DEFAULT_MODEL
        if not s.get("model") and model == DEFAULT_MODEL and not self._installed(url, model):
            model = FALLBACK_MODEL
        return model, url

    @staticmethod
    def _installed(url, model):
        try:
            names = {m["name"] for m in httpx.get(f"{url}/api/tags", timeout=3).json().get("models", [])}
        except Exception:
            return True  # let the real call report that Ollama is down
        return model in names or f"{model}:latest" in names

    def status(self) -> dict:
        model, url = self._cfg()
        out = {"model": model, "ready": False, "message": ""}
        try:
            tags = httpx.get(f"{url}/api/tags", timeout=3).json()
        except Exception:
            out["message"] = "Ollama is not running."
            return out
        names = {m["name"] for m in tags.get("models", [])}
        out["ready"] = model in names or f"{model}:latest" in names
        if not out["ready"]:
            out["message"] = f"Model not downloaded. Run: ollama pull {model}"
        return out

    def _body(self, messages, stream, temperature, max_tokens, schema=None):
        model, _ = self._cfg()
        body = {"model": model, "messages": messages, "stream": stream, "think": False,
                "keep_alive": KEEP_ALIVE,
                "options": {"temperature": temperature, "num_ctx": NUM_CTX, "num_predict": max_tokens}}
        if schema:
            body["format"] = schema
            # Qwen's default presence penalty punishes repeated JSON keys.
            body["options"]["presence_penalty"] = 0
        return body

    def chat(self, messages: list[dict], schema: dict | None = None, temperature: float = 0,
             max_tokens: int = 4096, timeout: float | None = None) -> str:
        """timeout: seconds; background jobs pass a long one because Ollama
        answers one request at a time and Papercut shares it."""
        _, url = self._cfg()
        r = httpx.post(f"{url}/api/chat", json=self._body(messages, False, temperature, max_tokens, schema),
                       timeout=httpx.Timeout(timeout, connect=10) if timeout else TIMEOUT)
        r.raise_for_status()
        return r.json()["message"]["content"]

    def stream(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 1500) -> Iterator[str]:
        _, url = self._cfg()
        with httpx.stream("POST", f"{url}/api/chat", json=self._body(messages, True, temperature, max_tokens),
                          timeout=TIMEOUT) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    msg = json.loads(line)
                    if text := msg.get("message", {}).get("content"):
                        yield text
                    if msg.get("done"):
                        break
