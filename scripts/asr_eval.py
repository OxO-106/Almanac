"""Compare speech models for Recordings on a hand-checked stretch of a real lecture.

    python scripts/asr_eval.py LECTURE --from 300 --to 480 --ref ref.txt [--course 13]
                               [--engines parakeet,qwen,qwen+vocab] [--with-35b]

LECTURE is any audio or video file; --from/--to pick the stretch (seconds) and
ref.txt is what was said in it, checked by ear, numbers in digits ("October 14"), fillers ("uh") left out,
names and course terms in brackets ("[Kimi Linear]"): those are scored apart.
If ref.txt doesn't exist, it is written as a draft from Parakeet (the model in
use, so the draft favours it, not the challenger) for the student to correct,
and nothing is scored.

Each engine is scored two ways on that stretch:
  final:  the whole stretch at once, as the final pass does
  live:   fed a second at a time through the real caption code (recordings._caption_once)
on word errors (WER), bracketed terms heard right, time per caption update
(over 1 s and captions fall behind), and GPU memory. "+vocab" gives the model
the course's vocabulary first (--course, recordings.vocabulary; Qwen only)."""
import argparse
import json
import re
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from app import recordings  # noqa: E402
from app.llm import DEFAULT_MODEL, DEFAULT_URL, KEEP_ALIVE  # noqa: E402
from app.transcriber import Parakeet  # noqa: E402

ENGINES = {"parakeet": (ROOT / ".venv-asr", 8021), "qwen": (ROOT / ".venv-qwen-asr", 8022)}
FILLERS = {"uh", "um", "er", "ah", "erm", "hmm", "mm"}  # not scored: the final pass removes them anyway
NUMBERS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                            "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}  # "two" is "2"
PIECE = recordings.SR * recordings.WIDTH  # bytes per second of audio: what the browser sends at a time


def words(text: str) -> list[str]:
    text = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", text.lower())  # "CS259" is "CS 259"
    return [NUMBERS.get(w, w) for w in re.sub(r"[^a-z0-9' ]+", " ", text.replace("-", " ")).split() if w not in FILLERS]


def wer(ref: list[str], hyp: list[str]) -> float:
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1] / max(1, len(ref))


def terms_heard(ref: str, hyp: str) -> tuple[list[str], list[str]]:
    """The bracketed terms of the reference: (heard right, missed). Spacing
    doesn't count ("G Q A" is "GQA"); each time a term is said counts."""
    squash = lambda text: "".join(words(text))
    left, right, missed = squash(hyp), [], []
    for term in re.findall(r"\[([^\]]+)\]", ref):
        if squash(term) in left:
            left = left.replace(squash(term), "|", 1)
            right.append(term)
        else:
            missed.append(term)
    return right, missed


def gpu_used() -> int:
    """MiB in use on the GPU."""
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True)
    return int(r.stdout.split()[0])


def cut(src: Path, start: float, end: float, out: Path):
    """The stretch as 16 kHz mono 16-bit PCM (ffmpeg from the speech environment)."""
    ffmpeg = subprocess.run([str(ENGINES["parakeet"][0] / "Scripts" / "python.exe"), "-c",
                             "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                            capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(src),
                    "-vn", "-ac", "1", "-ar", str(recordings.SR), "-f", "s16le", str(out)], check=True)


def as_wav(pcm: Path) -> Path:
    import wave
    out = pcm.with_suffix(".wav")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1), w.setsampwidth(recordings.WIDTH), w.setframerate(recordings.SR)
        w.writeframes(pcm.read_bytes())
    return out


def stop(t):
    """Stop a worker this script started: the whole tree (a venv's python.exe only launches the real one)."""
    if getattr(t, "proc", None):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(t.proc.pid)], capture_output=True)


class WithContext:
    """A transcriber that always reads `context` first (what _caption_once is handed)."""
    def __init__(self, t, context):
        self.t, self.context = t, context

    def window(self, pcm):
        return self.t.window(pcm, self.context)


def live(t, pcm: bytes, folder: Path) -> tuple[str, list[float]]:
    """Captions as the Recording page would show them at the end, and the seconds each update took."""
    path = folder / "live.pcm"
    path.write_bytes(b"")
    state = recordings.Live(path)
    took = []
    for i in range(0, len(pcm), PIECE):
        with open(path, "ab") as f:
            f.write(pcm[i:i + PIECE])
        t0 = time.perf_counter()
        try:
            recordings._caption_once(t, state)
        except Exception as e:  # as the caption thread does: shown, and the next update tries again
            print(f"  caption update at {i // PIECE} s failed after {time.perf_counter() - t0:.0f} s: {type(e).__name__} {e}")
        took.append(time.perf_counter() - t0)
    return " ".join([line["text"] for line in state.lines] + [state.partial]), took


def chat_model_loaded() -> bool:
    return any(m["name"] == DEFAULT_MODEL for m in httpx.get(f"{DEFAULT_URL}/api/ps", timeout=10).json()["models"])


def chat_model(load: bool):
    """Load the 35B onto the GPU, or take it off (as during a lecture: the GPU is the speech model's)."""
    httpx.post(f"{DEFAULT_URL}/api/generate", json={"model": DEFAULT_MODEL, "keep_alive": KEEP_ALIVE if load else 0}, timeout=300)


def run(name: str, pcm_path: Path, wav: Path, context: str) -> dict:
    venv, port = ENGINES[name]
    t = Parakeet(port, name, venv / "Scripts" / "python.exe")
    before, t0 = gpu_used(), time.perf_counter()
    t._ensure()
    started = time.perf_counter() - t0
    try:
        t0 = time.perf_counter()
        segments, seconds = t.file(wav, context)
        final_s = time.perf_counter() - t0
        memory = gpu_used() - before
        caption, took = live(WithContext(t, context), pcm_path.read_bytes(), pcm_path.parent)
    finally:
        stop(t)
    return {"final": " ".join(s["text"] for s in segments), "live": caption, "start_s": started,
            "final_x": seconds / final_s, "took": took, "memory": memory}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lecture", type=Path)
    ap.add_argument("--from", dest="start", type=float, required=True)
    ap.add_argument("--to", dest="end", type=float, required=True)
    ap.add_argument("--ref", type=Path, required=True)
    ap.add_argument("--course", type=int, help="course id, for its vocabulary")
    ap.add_argument("--engines", default="parakeet,qwen,qwen+vocab")
    ap.add_argument("--with-35b", action="store_true", help="load the chat model first, as during a real lecture")
    a = ap.parse_args()

    vocab = []
    if a.course is not None:
        con = sqlite3.connect(ROOT / "data" / "almanac.db")
        con.row_factory = sqlite3.Row
        vocab = recordings.vocabulary(con, a.course)

    with tempfile.TemporaryDirectory() as tmp:
        pcm = Path(tmp) / "stretch.pcm"
        cut(a.lecture, a.start, a.end, pcm)
        wav = as_wav(pcm)
        if not a.ref.exists():
            venv, port = ENGINES["parakeet"]
            t = Parakeet(port, "parakeet", venv / "Scripts" / "python.exe")
            segments, _ = t.file(wav)
            a.ref.write_text("\n".join(s["text"] for s in segments) + "\n", encoding="utf-8")
            stop(t)
            print(f"Wrote a draft to {a.ref} (Parakeet's reading). Listen to {a.start:.0f}-{a.end:.0f} s, correct it, run again.")
            return
        ref = a.ref.read_text(encoding="utf-8")
        chat_model(a.with_35b)
        print(f"{a.lecture.name}, {a.start:.0f}-{a.end:.0f} s: {len(words(ref))} words, "
              f"{ref.count('[')} bracketed terms; "
              f"{len(vocab)} vocabulary terms; GPU {gpu_used()} MiB in use before"
              + (" with the 35B loaded" if a.with_35b else " with the 35B off the GPU"))
        rows = []
        for engine in a.engines.split(","):
            name = engine.removesuffix("+vocab")
            context = "Course vocabulary: " + "; ".join(vocab) if engine.endswith("+vocab") else ""
            chat_model(a.with_35b)
            r = run(name, pcm, wav, context)
            r["chat_model_loaded"] = chat_model_loaded()
            if r["chat_model_loaded"] != a.with_35b:
                print(f"  warning: the 35B was {'loaded by something else' if r['chat_model_loaded'] else 'unloaded'} during {engine}")
            a.ref.with_suffix(f".{engine}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
            for mode in ("final", "live"):
                right, missed = terms_heard(ref, r[mode])
                rows.append((engine, mode, wer(words(ref), words(r[mode])), right, missed, r))
        print(f"\n{'engine':<14}{'mode':<7}{'WER':>7}{'terms':>8}   speed")
        for engine, mode, w, right, missed, r in rows:
            speed = (f"{r['final_x']:.0f}x real time; started in {r['start_s']:.0f} s; +{r['memory']} MiB GPU" if mode == "final" else
                     f"caption update median {statistics.median(r['took']):.2f} s, worst {max(r['took']):.2f} s, "
                     f"{sum(x > 1 for x in r['took'])} of {len(r['took'])} over 1 s")
            print(f"{engine:<14}{mode:<7}{w:>6.1%}{len(right):>4}/{len(right) + len(missed):<3}   {speed}")
        for engine, mode, w, right, missed, r in rows:
            print(f"\n--- {engine}, {mode}" + (f"; missed terms: {', '.join(missed)}" if missed else ""))
            print(r[mode])


if __name__ == "__main__":
    main()
