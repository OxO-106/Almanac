# 01: Parakeet transcriber on the PC

**What to build:** A transcriber that turns audio into English text with segment times, using NVIDIA Parakeet TDT 0.6B v2 on the PC's GPU, in its own worker process that the server starts when needed and stops when idle. Two modes: live (a rolling window of the last few seconds → caption text, about once a second) and final (a whole file → segments with start/end times). First decide the runtime by measuring: NeMo (official; pulls PyTorch with CUDA, several GB) vs a lighter ONNX runtime for Parakeet, on accuracy, speed, GPU memory and install size.

**Blocked by:** none (needs the student's OK for the downloads: the model is about 1.2 GB, plus the runtime)

**Status:** done

- [x] Runtime chosen with numbers (see Comments). Word errors on a hand-checked minute: still to do by the student (listening); a reading of the output is below
- [x] Final mode: a 1-hour file transcribes in a few minutes or less; segments carry start/end seconds
- [x] Live mode: text for the last window within about a second of the audio arriving, while the 35B is loaded
- [x] The worker loads Parakeet on first use and frees the GPU when no Recording has needed it for a few minutes
- [x] Tests run without the model: the cutting logic is tested; a fake transcriber for the server comes with ticket 02, which first calls it

## Comments

2026-10-02. Clip: 15 min 42 s of the student's CS 259 online lecture (Potkonjak), screen recording, accented speaker.

**Runtime: onnx-asr (ONNX Runtime GPU), not NeMo.** Same Parakeet weights, so the same accuracy; NeMo would add about 3 GB of PyTorch and a Linux-first toolkit for nothing the ONNX path lacks. Not downloaded. The int8 model is out: its parts don't run on the GPU (25x slower on the CPU).

| | alone on the GPU | with the 35B loaded |
|---|---|---|
| whole clip (20 s windows, batched) | 4.5 s (211x real time) | 9.7 s (97x) |
| a 3 s live window (model only) | 80 ms | 116 ms |
| a 3 s live window through `app/transcriber.py` | | 109 ms median, 123 ms worst |
| GPU memory | +3.7 GB | Windows spills into shared memory; both fit |
| the 35B's speed afterwards | | 67 tokens/s (unchanged) |

So the trade-off in the spec's "GPU goes to captions" mostly disappears: chat isn't measurably slower during a lecture. First worker start (model load) about 8-20 s.

**Long recordings are cut, not VAD-split.** onnx-asr's VAD path ran on the CPU (81 s for the clip, 12x) and split mid-sentence ("Wouldst thy wildest" for "first I will talk"). Cutting about every 20 s at the quietest 30 ms frame within 8 s gave better text ("Miodrak Potkonyak" vs "Miel Drak Portcogniak"; the instructor is Miodrag Potkonjak, which ticket 02's course vocabulary will fix).

Built: `asr/worker.py` (runs in `.venv-asr`, HTTP on 127.0.0.1:8011: `/window` for Captions, `/file` for any audio or video via ffmpeg, exits after 5 idle minutes), `app/transcriber.py` (starts the worker on first use, no console window), `asr/requirements.txt` (how to recreate the environment). `python -m app.transcriber <file>` transcribes one file.
