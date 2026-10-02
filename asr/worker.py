"""Speech to text with NVIDIA Parakeet TDT 0.6B v2 (ONNX, on the GPU).

Runs in its own environment (.venv-asr: the speech runtime is large and kept
out of the web server) as a small HTTP server on 127.0.0.1. Almanac starts it
when a Recording needs it (app/transcriber.py); it exits after IDLE seconds
unused, which frees the GPU.

  POST /window  body: 16 kHz mono int16 PCM      → {"text"}       (Captions)
  POST /file    {"path": any audio or video}     → {"segments": [{"start", "end", "text"}], "seconds"}
  GET  /health                                   → {"ready": true}

Measured on the 4070 Ti Super with the 35B loaded (ticket 01): a 3 s window
in about 0.1 s; a whole lecture at about 100x real time."""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SR = 16000
FRAME = 0.03     # seconds per energy frame when looking for a quiet place to cut
WINDOW = 20      # a long recording is transcribed in windows of about this many seconds,
SPREAD = 8       # each cut at the quietest moment within this many seconds of the target
BATCH = 16
IDLE = int(os.environ.get("ALMANAC_ASR_IDLE", 300))  # seconds unused before it stops
MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "models" / "parakeet-tdt-0.6b-v2"


def quiet_cuts(energy: list[float], frame: float = FRAME, window: float = WINDOW, spread: float = SPREAD) -> list[int]:
    """Frame indexes to cut a recording at: about every `window` seconds, at the
    quietest frame within `spread` seconds of the target, so no word is split."""
    cuts, start, n = [], 0, len(energy)
    per, near = int(window / frame), int(spread / frame)
    while n - start > per + near:
        lo, hi = start + per - near, start + per + near
        cut = min(range(lo, hi), key=lambda i: energy[i])
        cuts.append(cut)
        start = cut
    return cuts


def main(port: int):
    import numpy as np
    import onnxruntime as ort
    ort.preload_dlls()  # CUDA and cuDNN from pip
    import imageio_ffmpeg
    import onnx_asr

    model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", str(MODEL_DIR),
                                providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    model.recognize(np.zeros(SR, np.float32), sample_rate=SR)  # load the GPU kernels now, not on the first caption
    gpu = threading.Lock()  # one job on the GPU at a time
    last = [time.time()]

    def decode(path) -> "np.ndarray":
        """Any audio or video file → 16 kHz mono float samples (ffmpeg says what's wrong if it can't)."""
        r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-i", str(path),
                            "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True)
        if r.returncode:
            raise ValueError(f"ffmpeg couldn't read the audio: {r.stderr.decode(errors='replace').strip()[-300:]}")
        return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768

    def transcribe(audio) -> list[dict]:
        step = int(FRAME * SR)
        frames = len(audio) // step
        energy = (audio[: frames * step].reshape(frames, step) ** 2).mean(axis=1).tolist() if frames else []
        bounds = [0] + [c * step for c in quiet_cuts(energy)] + [len(audio)]
        pieces = [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a > SR // 10]
        segments = []
        for i in range(0, len(pieces), BATCH):
            batch = pieces[i:i + BATCH]
            with gpu:
                texts = model.recognize([audio[a:b] for a, b in batch], sample_rate=SR)
            segments += [{"start": round(a / SR, 2), "end": round(b / SR, 2), "text": t.strip()}
                         for (a, b), t in zip(batch, texts) if t.strip()]
        return segments

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # asking whether it's up isn't using it: it still stops when idle
            self.reply(200, {"ready": True}) if self.path == "/health" else self.reply(404, {"error": "not found"})

        def do_POST(self):
            last[0] = time.time()
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                if self.path == "/window":
                    audio = np.frombuffer(body, dtype=np.int16).astype(np.float32) / 32768
                    with gpu:
                        text = model.recognize(audio, sample_rate=SR) if len(audio) > SR // 10 else ""
                    self.reply(200, {"text": text.strip()})
                elif self.path == "/file":
                    audio = decode(json.loads(body)["path"])
                    self.reply(200, {"segments": transcribe(audio), "seconds": round(len(audio) / SR, 2)})
                else:
                    self.reply(404, {"error": "not found"})
            except Exception as e:
                self.reply(500, {"error": f"{type(e).__name__}: {e}"})
            last[0] = time.time()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    def idle():
        while time.time() - last[0] < IDLE:
            time.sleep(5)
        os._exit(0)  # unused for a while: free the GPU

    threading.Thread(target=idle, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8011)
