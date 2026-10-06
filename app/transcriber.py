"""Speech to text for Recordings, through the Parakeet worker (asr/worker.py).

The worker runs in its own environment, .venv-asr, so the speech runtime stays
out of this process; it is started on first use and stops itself when idle,
freeing the GPU. Tests use a fake with the same methods (tests/conftest.py)."""
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv-asr" / "Scripts" / "python.exe"
WORKER = ROOT / "asr" / "worker.py"
PORT = 8011  # Papercut is 8000, Almanac 8001
START_TIMEOUT = 90  # seconds: loading the model onto the GPU


class Parakeet:
    def __init__(self, port: int = PORT, engine: str = "parakeet", python: Path = PYTHON):
        self.url = f"http://127.0.0.1:{port}"
        self.port, self.engine, self.python = port, engine, python
        self._starting = threading.Lock()
        self._client = httpx.Client()  # one kept-alive connection: Captions call it every second

    def status(self) -> dict:
        if not self.python.exists():
            return {"ready": False, "message": "The speech environment (.venv-asr) isn't installed."}
        try:
            httpx.get(f"{self.url}/health", timeout=2).raise_for_status()
            return {"ready": True, "message": "Running"}
        except httpx.HTTPError:
            return {"ready": True, "message": "Starts when a Recording needs it"}

    def _ensure(self):
        """Start the worker if it isn't running, and wait until the model is loaded."""
        with self._starting:
            try:
                httpx.get(f"{self.url}/health", timeout=2).raise_for_status()
                return
            except httpx.HTTPError:
                pass
            if not self.python.exists():
                raise RuntimeError("The speech environment (.venv-asr) isn't installed.")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = self.proc = subprocess.Popen([str(self.python), str(WORKER), str(self.port), self.engine], cwd=ROOT, creationflags=flags,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            deadline = time.time() + START_TIMEOUT
            while time.time() < deadline:
                if proc.poll() is not None:
                    err = proc.stderr.read().decode(errors="replace").strip().splitlines()
                    raise RuntimeError("The speech worker stopped while starting: " + (err[-1] if err else f"exit {proc.returncode}"))
                try:
                    httpx.get(f"{self.url}/health", timeout=2).raise_for_status()
                    return
                except httpx.HTTPError:
                    time.sleep(0.5)
            proc.kill()
            raise RuntimeError(f"The speech worker didn't start within {START_TIMEOUT} s.")

    def _post(self, path, timeout, **kw) -> dict:
        try:
            r = self._client.post(f"{self.url}{path}", timeout=timeout, **kw)
        except httpx.ConnectError:  # not running (first use, or it stopped when idle): start it
            self._ensure()
            r = self._client.post(f"{self.url}{path}", timeout=timeout, **kw)
        if r.status_code >= 400:
            raise RuntimeError(r.json().get("error") or r.text)
        return r.json()

    def window(self, pcm16: bytes, context: str = "") -> str:
        """Text of a few seconds of 16 kHz mono int16 audio (Captions)."""
        return self._post("/window", 30, content=pcm16, params={"context": context} if context else None)["text"]

    def file(self, path, context: str = "") -> tuple[list[dict], float]:
        """([{"start", "end", "text"}], seconds) for a whole audio or video file."""
        r = self._post("/file", 1800, json={"path": str(Path(path).resolve()), "context": context})
        return r["segments"], r["seconds"]


if __name__ == "__main__":  # python -m app.transcriber <file>: transcribe one file
    sys.stdout.reconfigure(encoding="utf-8")
    t = time.time()
    segments, seconds = Parakeet().file(sys.argv[1])
    print(f"{seconds:.0f} s of audio in {time.time() - t:.1f} s, {len(segments)} segments")
    for s in segments:
        print(f"[{s['start']:7.1f}-{s['end']:7.1f}] {s['text']}")
