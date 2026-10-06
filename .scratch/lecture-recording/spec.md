# Lecture recording: captions, transcripts and notes

Status: phases 1-3 built (2026-10-02): tickets 01-15 done; the laptop checks in 05 and 07 are the student's. Phase 4 not started.

Vocabulary (in `CONTEXT.md`): **Recording**, **Captions**, **Transcript**, **Jotting**, **Lecture notes**, **Lecture kind** (Paper session, Concept lecture, Presentation day).

## Why

The student takes two classes online and the rest in person, and wants an
assistant that helps them learn during and after a lecture: captions while it
runs, a clean record afterwards, notes built on what they jotted, and the
plan kept current with what the lecturer announced. It is a feature of
Almanac, not a separate app: the point is the interaction with the plan and
chat, not an archive of audio.

## What it is

A lecture assistant inside Almanac for in-person lectures (the microphone)
and online lectures, live or replayed (the device's audio). Recorded on the
laptop (mostly) or the PC; the phone can read along. English only. Speech is
transcribed on the PC with **NVIDIA Parakeet TDT 0.6B v2**; everything smart is
the 35B (`qwen3.5:35b-a3b`, see `app/llm.py`). Conversations (office hours,
team meetings) are out of scope: consent.

## Decisions

### During the lecture

- **Captions** (rough is fine: they're for following along) shown either on the
  Recording page beside the Jottings (a Notion-AI-meeting-notes-like layout:
  captions on one side, the student's notes on the other) or in a floating
  always-on-top caption window over the lecture video (Document
  Picture-in-Picture, Chrome/Edge). The student chooses each time.
- **Jottings**: lines the student types, each silently stamped with the moment
  in the lecture; a **Mark** key adds a bare one ("this matters").
- Nothing else smart until the lecture ends.
- **The GPU goes to captions**: Parakeet stays loaded for the whole Recording;
  Ollama moves part of the 35B off the GPU, so chat is slower meanwhile.
- **Start** suggests the course (the class happening now, else one whose
  "watch the recording" task is open), the Lecture kind and the audio source
  (device audio for an online class or a replay, else the microphone); one tap
  to change any. Never both sources at once.
- **Pause** (class breaks). **Auto-stop** after 10 minutes of silence, and 15
  minutes past the class's end for a class happening now; a notification says so.
- Audio goes to the PC in chunks as it's recorded (a second or two buffered
  in the browser), so a dropped connection doesn't lose it.

### After the lecture

- **Final pass**: Parakeet transcribes the full audio again (better than the
  live chunks), then the 35B cleans it: fillers, stutters and repeats out,
  broken sentences completed, the lecturer's words otherwise kept. Terms are
  corrected against the course's vocabulary (paper titles, topics and terms
  from its syllabus and reading list): "Kimmy linear" → "Kimi Linear". A word
  that matches nothing stays as heard; anything still uncertain is marked in
  the text.
- **The audio is then deleted, automatically**, everywhere. The clean
  **Transcript** is the record (ADR 0001). It is kept (collapsed under the
  notes, with a Delete button): it's tiny and it's what later questions search.
- **Questions in chat** only when something plan-relevant is unclear (a date,
  deadline, assignment, exam, reading): "Kim said the proposal is due 'the
  fourteenth or so'. Is it Oct 14?" Everything else uncertain is marked, not asked.
- **Lecture notes**, built on the Jottings: the student's lines kept as written
  (shown as theirs) and filled in from the Transcript, plus what they didn't
  jot. Keep everything important; length doesn't matter (one-pagers and other
  artifacts come later). They end with what was announced, if anything was. By Lecture kind:
  - **Paper session** (CS 259, both CS 239s this quarter), in this order
    (changed 2026-10-06 at the student's request): **Takeaways** of each of
    the lecture's papers, also those not presented; a **Comparison** table of
    all of them; their **Connections** (each says whether it was stated in
    class or in a paper); **Background** from class and from the papers;
    **Questions** asked in class with their answers; a one-paragraph
    **Summary** of the lecture; **Announced**, only if anything was. What a
    paper says comes from Papercut's library, read-only (`app/papers.py`:
    its abstract, summary and section headings); a paper not in the library
    is known by its title only.
    What must be true is settled by code (2026-10-06, after the model invented
    an assignment, office hours and a Q&A answer): class notes are written from
    the Transcript alone, then composed with the papers (Takeaways split into
    **In class** / **From the paper**); a paper the Transcript never names is
    marked "Not presented in class"; each Question's words, and its answer's,
    must be found in the Transcript, followed by **From the paper**, an answer
    from the paper's own passages, quoted and checked; **Announced** is built
    from `announcements.find` (the same quote-checked items that become
    Proposals), never written by the notes model.
  - **Concept lecture** (CS 269): concepts, definitions, walk-throughs.
  - **Presentation day**: feedback on the student's own work (actionable
    points become Proposals), a line or two on each other project.
  - Speakers by role only ("a student asked", "the presenter answered",
    "Prof. Ding added"); no classmates' names, no voice identification.
- **Lecture kind is read from the syllabus**: the schedule row for that date
  (papers listed → Paper session; a project milestone or presentation →
  Presentation day), else the course's usual kind, also read from the
  syllabus. Nothing per course is hard-coded: next quarter's courses get theirs
  from their syllabi.
- **What the lecturer announces** becomes Proposals with the Transcript quote
  and the lecture's date; the lecture wins over the syllabus (it's newer), as
  chat corrections do.
- **Notes are the student's**: freely editable; the assistant changes them only
  when asked, from the lecture page ("shorter", "add the derivation") or from
  Chat, applied at once with **Undo**.
- **Where**: each course page gets a **Lectures** list by date; a lecture shows
  its notes, the Transcript collapsed, and its Proposals.
- A replay ticks off its "watch the recording" task.

### When the PC can't be reached

Almanac is served by the PC, so the Recording page needs it. Almanac keeps the
PC awake during scheduled classes (and for an hour after a replay starts).
Otherwise the student records with the laptop (Sound Recorder; OBS for device
audio) and **uploads the file** later: same final pass, notes and deletion, no
captions. Upload also brings in phone voice memos and Zoom downloads. (A
cached, offline Recording page is possible later if this proves common.)

## Shape (to be confirmed by ticket 01)

- **Browser**: `getUserMedia` (microphone) or `getDisplayMedia` with audio
  (a tab or the screen); 16 kHz mono chunks over a WebSocket to the server.
  Tailscale's HTTPS address makes it a secure context.
- **Transcriber**: Parakeet in its own worker process on the PC (its runtime
  is heavy; keep it out of the web server's process and load it only while
  needed). Live: rolling windows → Captions. Final: the whole file.
- **Storage**: a `recordings` row per Recording (course, kind, times, status,
  Jottings with offsets, Transcript with segment times, notes); the audio as
  a temporary file under `data/` until the final pass is done. A Recording is
  a Source, so Proposals and Questions work as for documents and chat.

## Phases

1. **Record, caption, transcribe** (tickets 01-09): the transcriber, file
   upload with the final pass, Lecture kinds from the syllabus, the Lectures
   list, the live Recording page with Captions, Jottings, Mark, Pause and
   sources, the floating caption window, auto-stop and keeping the PC awake,
   phone read-along.
2. **Smart after the lecture**: Lecture notes by kind, announcements →
   Proposals, chat questions, replay ticks its task.
3. **Living notes**: change requests (lecture page and Chat) with Undo.
4. **Later**: asking across lectures, one-pagers and study material,
   translation, live "ask about the lecture".

## Not doing

Conversations or speaker identification; keeping audio; recording on the
phone's browser (it stops when the screen locks: use the phone's recorder and
upload); both audio sources at once; recording the student's own talk for
delivery coaching.
