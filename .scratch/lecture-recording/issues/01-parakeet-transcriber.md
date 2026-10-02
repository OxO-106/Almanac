# 01: Parakeet transcriber on the PC

**What to build:** A transcriber that turns audio into English text with segment times, using NVIDIA Parakeet TDT 0.6B v2 on the PC's GPU, in its own worker process that the server starts when needed and stops when idle. Two modes: live (a rolling window of the last few seconds → caption text, about once a second) and final (a whole file → segments with start/end times). First decide the runtime by measuring: NeMo (official; pulls PyTorch with CUDA, several GB) vs a lighter ONNX runtime for Parakeet, on accuracy, speed, GPU memory and install size.

**Blocked by:** none (needs the student's OK for the downloads: the model is about 1.2 GB, plus the runtime)

**Status:** ready-for-human (download approval), then ready-for-agent

- [ ] Runtime chosen with numbers: a 10-15 min real lecture clip transcribed by each candidate; time, GPU memory with the 35B loaded, word errors on a hand-checked minute
- [ ] Final mode: a 1-hour file transcribes in a few minutes or less; segments carry start/end seconds
- [ ] Live mode: text for the last window within about a second of the audio arriving, while the 35B is loaded (Ollama may move part of it off the GPU: measured, not assumed)
- [ ] The worker loads Parakeet on first use and frees the GPU when no Recording has needed it for a few minutes
- [ ] Tests run without the model (a fake transcriber), like FakeLLM

## Comments
