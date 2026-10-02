# 02: Upload a recording; the final pass makes a Transcript

**What to build:** Upload an audio file (phone voice memo, Zoom download, Sound Recorder or OBS file) as a Recording of a course's lecture. The final pass transcribes it with ticket 01, then the 35B cleans it in chunks: fillers, stutters and repeats out, broken sentences completed, the lecturer's words otherwise kept, terms corrected against the course vocabulary (paper titles, reading list, topics and terms from its syllabus). A word that matches nothing stays as heard; what's still uncertain is marked. Then the audio is deleted (ADR 0001). The Recording is a Source.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Upload accepts common audio (m4a, mp3, wav, webm, ogg) and asks which course (suggesting one whose "watch the recording" task is open) and date
- [ ] The Transcript keeps segment times; Jotting offsets (ticket 06) will land on it
- [ ] Course vocabulary fixes names the transcriber mangles (test: "Kimmy linear" → "Kimi Linear" when Kimi Linear is on the reading list); an unmatched word is left alone
- [ ] The audio file is gone from disk once the Transcript is saved, and also when the pass fails (the failure says what went wrong; the student re-uploads)
- [ ] Progress and "Transcript ready" notifications, like document reading
- [ ] Measured on a real lecture: a hand-checked passage, before and after clean-up

## Comments
