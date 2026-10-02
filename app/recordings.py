"""Recordings: a lecture's audio becomes a clean Transcript (see
.scratch/lecture-recording/spec.md and docs/adr/0001).

The final pass: the transcriber (Parakeet) turns the audio into timed
segments, the audio is deleted, then the model cleans the text a few segments
at a time (fillers, stutters and repeats out, broken sentences completed),
correcting names and terms against the course's vocabulary. The uncleaned
text is kept only until the clean-up is done."""
import json
import re
import threading
import time
import wave
from array import array
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile

from . import plan
from .clock import local
from .db import WRITE
from .scheduler import WATCHERS, notify

router = APIRouter(prefix="/api")

AUDIO = {".m4a", ".mp3", ".wav", ".webm", ".ogg", ".opus", ".flac", ".aac", ".mp4", ".mov", ".mkv"}
CHUNK_CHARS = 2500  # uncleaned text per clean-up call: a few minutes of speech
KEPT = 0.5          # a cleaned segment keeping fewer of its words than this lost content: the uncleaned one is used

CLEAN_PROMPT = """You clean up a lecture transcript made by speech recognition, for a student's notes. For each numbered segment, return the same speech, cleaned:
- Remove fillers ("uh", "um", "you know", "like" as a filler), stutters, repeated words and false starts.
- Complete broken sentences and fix punctuation and capitals, keeping the lecturer's words and meaning.
- Never add anything that wasn't said, never summarize, never drop content.
- Speech recognition mishears names and technical terms. When words sound like a term in the course vocabulary below, write the term (for example "Kimmy linear" → "Kimi Linear", "G Q A" → "GQA"). Change a word only when it clearly matches.
- If a word is unclear and matches nothing, keep it as heard and put [?] right after it.
Segments may begin or end mid-sentence; keep each segment's speech in that segment."""

CLEAN_SCHEMA = {"type": "object", "properties": {"segments": {"type": "array", "items": {"type": "object", "properties": {
    "n": {"type": "integer"}, "text": {"type": "string"}}, "required": ["n", "text"]}}}, "required": ["segments"]}

_TERM = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*\b")


def vocabulary(con, course_id) -> list[str]:
    """Names and terms a lecture of this course will use, from what Almanac knows:
    the course and instructor, its plan items (paper titles from the reading
    list), and the distinctive words of its documents (acronyms, CamelCase,
    words with digits, and proper nouns: capitalized and never written in
    lower case there)."""
    c = con.execute("select * from courses where id = ?", (course_id,)).fetchone() if course_id is not None else None
    if not c:
        return []
    terms = [c["number"], c["instructor"]] + ([c["title"]] if c["title"] else [])
    for table in ("tasks", "deadlines", "events", "projects"):
        terms += [re.sub(r"^(read|review|skim)\s+", "", r["title"], flags=re.I)
                  for r in con.execute(f"select title from {table} where course_id = ?", (course_id,))]
    texts = [r["text"] for r in con.execute(f"select text from sources where kind = 'document' and replaced_by is null "
                                            f"and id in ({','.join('?' * len(ids))})", ids)] if (ids := _course_sources(con, c)) else []
    for text in texts:
        words = _TERM.findall(text)
        lower = {w for w in words if w.islower()}
        # a name is capitalized mid-sentence ("the Turing Award"); a heading word only starts lines ("Grading")
        inside = {m[1] for m in re.finditer(r"[a-z,;]\s+([A-Z][a-z]+)", text)}
        for w in words:
            distinctive = (any(ch.isdigit() for ch in w) or (w.isupper() and len(w) > 1)
                           or any(ch.isupper() for ch in w[1:]))
            proper = w[0].isupper() and w[1:].islower() and len(w) > 2 and w.lower() not in lower and w in inside
            if distinctive or proper:
                terms.append(w)
    seen, out = set(), []
    for t in terms:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:600]


def _course_sources(con, c) -> list[int]:
    """The documents a course came from: the one that added the course, those that
    added its items, and any labelled with it (code and instructor)."""
    ids = set()
    for kind, rows in [("courses", [c["id"]])] + [
            (t, [r["id"] for r in con.execute(f"select id from {t} where course_id = ?", (c["id"],))])
            for t in ("tasks", "deadlines", "events", "projects")]:
        for i in rows:
            if (o := plan.origin(con, kind, i)) and o.get("source_id"):
                ids.add(o["source_id"])
    surname = c["instructor"].split()[-1] if c["instructor"] else ""
    ids |= {r["id"] for r in con.execute("select id, about from sources where about is not null")
            if c["number"] in r["about"] and surname and surname in r["about"]}
    return sorted(ids)


KIND_NAMES = {"paper_session": "Paper session", "concept_lecture": "Concept lecture", "presentation_day": "Presentation day"}


def lecture_kind(con, course_id, day: str) -> dict | None:
    """{"kind", "papers", "quote"} for this course's lecture on `day`, from its
    syllabus: that date's row, a week containing it, else the course's usual kind."""
    c = con.execute("select * from courses where id = ?", (course_id,)).fetchone() if course_id is not None else None
    ids = _course_sources(con, c) if c else []
    if not ids:
        return None
    rows = con.execute(f"select * from lecture_kinds where source_id in ({','.join('?' * len(ids))}) and source_id in "
                       f"(select id from sources where replaced_by is null) order by id", ids).fetchall()
    exact = [r for r in rows if r["date"] == day]
    week = [r for r in rows if r["date"] and "/" in r["date"] and r["date"][:10] <= day <= r["date"][-10:]]
    usual = [r for r in rows if r["date"] is None]
    r = (exact or week or usual or [None])[0]
    return r and {"kind": r["kind"], "papers": json.loads(r["papers"]) if r["papers"] else [], "quote": r["quote"]}


def _chunks(segments):
    out, cur, size = [], [], 0
    for i, s in enumerate(segments):
        if cur and size + len(s["text"]) > CHUNK_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(s["text"])
    return out + [cur] if cur else out


def clean(llm, segments, vocab) -> list[dict]:
    """The cleaned segments, same times. Judged a chunk (a few minutes) at a time:
    the model may move a few words across a segment boundary to finish a
    sentence, so a chunk is kept when it kept its content as a whole; a chunk
    cleaned down to too few words (summarized) stays as transcribed."""
    words = lambda t: len(re.findall(r"\w+", t))
    out = [dict(s) for s in segments]
    system = CLEAN_PROMPT + "\n\nCourse vocabulary: " + ("; ".join(vocab) or "none")
    for idx in _chunks(segments):
        listing = "\n".join(f"{n}. {segments[i]['text']}" for n, i in enumerate(idx))
        try:
            got = json.loads(llm.chat([{"role": "system", "content": system}, {"role": "user", "content": listing}],
                                      schema=CLEAN_SCHEMA, timeout=600))["segments"]
        except Exception:
            continue  # this part stays as transcribed
        texts = {g["n"]: (g.get("text") or "").strip() for g in got if isinstance(g.get("n"), int) and 0 <= g["n"] < len(idx)}
        if sum(map(words, texts.values())) < KEPT * sum(words(segments[i]["text"]) for i in idx):
            continue
        for n, i in enumerate(idx):
            heard = " ".join(segments[idx[k]]["text"] for k in range(max(0, n - 1), min(len(idx), n + 2)))
            out[i]["text"] = _doubtful_terms(texts.get(n, ""), heard, vocab)
    return [s for s in out if s["text"]]  # a segment whose words all moved to its neighbour


LIKE = 0.6  # how alike a heard word and the course term put in its place must be to trust the swap


def _doubtful_terms(cleaned: str, heard: str, vocab) -> str:
    """Mark [?] a course term the clean-up wrote where nothing like it was said:
    "computer science" → "Achievements in Computer Science" (words added from
    the course title). Fixes pass: "Potkonyak" → "Potkonjak", "G Q A" → "GQA",
    and a name heard as another name ("call me Mayu" → "call me Miodrag": the
    student wants the course's names used). The two texts are lined up word by
    word, so a term is compared only with what was heard in its place."""
    names = {w.lower() for t in vocab for w in re.findall(r"[\w'-]+", t) if len(w) > 2}
    heard_raw = re.findall(r"[\w'-]+", heard)
    heard_w = [w.lower() for w in heard_raw]
    found = list(re.finditer(r"[\w'-]+", cleaned))
    like = lambda a, b: SequenceMatcher(None, a, b).ratio() >= LIKE
    doubtful = set()
    ops = SequenceMatcher(None, heard_w, [m.group(0).lower() for m in found], autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag not in ("replace", "insert"):
            continue
        was = heard_w[i1:i2]
        a_name = tag == "replace" and all(w[:1].isupper() for w in heard_raw[i1:i2])  # a name heard in its place
        for k in range(j1, j2):
            w = found[k].group(0).lower()
            # heard nearby as it is ("computer science" said, written "Computer Science"): fine, however it aligned
            if w in names and w not in heard_w and not a_name and not any(like(w, x) for x in was + ["".join(was)]):
                doubtful.add(k)
    out, last = [], 0
    for k, m in enumerate(found):
        out.append(cleaned[last:m.end()])
        last = m.end()
        if k in doubtful and not cleaned[m.end():].startswith(" [?]"):
            out.append(" [?]")
    return "".join(out) + cleaned[last:]


def _set(con, rec_id, **fields):
    with WRITE:
        con.execute(f"update recordings set {', '.join(f'{k} = ?' for k in fields)} where id = ?", (*fields.values(), rec_id))


def finalize(con, llm, clock, transcriber, rec_id, audio: Path):
    """The final pass for one Recording. The audio is deleted whatever happens."""
    rec = con.execute("select * from recordings where id = ?", (rec_id,)).fetchone()
    label = _label(con, rec)
    try:
        try:
            segments, seconds = transcriber.file(audio)
        finally:
            Path(audio).unlink(missing_ok=True)  # ADR 0001: the audio never outlives transcription
        if not segments:
            raise ValueError("No speech was found in the recording.")
        _set(con, rec_id, status="cleaning", seconds=seconds, pending=json.dumps(segments))
        done = clean(llm, segments, vocabulary(con, rec["course_id"]))
        _set(con, rec_id, status="done", transcript=json.dumps(done), pending=None)
        with WRITE:
            con.execute("update sources set text = ?, status = 'done' where id = ?",
                        ("\n".join(s["text"] for s in done), rec["source_id"]))
        notify(con, clock, "recording", "Transcript ready", f"{label}: {round(seconds / 60)} min transcribed. Writing the notes now.",
               f"#lecture/{rec_id}")
        from . import lecture_notes  # it builds on this module
        lecture_notes.after_transcript(con, llm, clock, rec_id)
    except Exception as e:
        msg = str(e) if isinstance(e, (ValueError, RuntimeError)) else f"{type(e).__name__}: {e}"
        _set(con, rec_id, status="failed", error=msg)
        with WRITE:
            con.execute("update sources set status = 'failed', error = ? where id = ?", (msg, rec["source_id"]))
        notify(con, clock, "recording", f"Couldn't transcribe {label}", msg, f"#lecture/{rec_id}")


def _label(con, rec) -> str:
    c = con.execute("select number, instructor from courses where id = ?", (rec["course_id"],)).fetchone() if rec["course_id"] else None
    who = f"{c['number']} · {c['instructor'].split()[-1]}" if c else "Lecture"
    return f"{who}, {rec['date']}"


def recover(con, folder: Path):
    """After a restart: audio left by an interrupted pass is deleted, and its
    Recording says so (ADR 0001: no audio outlives its pass)."""
    running = {f"{r['id']}.pcm" for r in con.execute("select id from recordings where status = 'recording'")}
    if folder.exists():
        for f in folder.iterdir():
            if f.name not in running:  # a live Recording goes on: the browser keeps sending
                f.unlink(missing_ok=True)
    with WRITE:
        con.execute("update recordings set status = 'failed', error = 'Almanac stopped while transcribing it. "
                    "Upload the recording again.' where status in ('transcribing', 'cleaning') and pending is null")
    for r in con.execute("select id from recordings where status = 'cleaning' and pending is not null").fetchall():
        _set(con, r["id"], status="failed", error="Almanac stopped while cleaning the transcript. Try again.")
    with WRITE:  # notes interrupted: written ones can be written again; a change wasn't made
        con.execute("update recordings set notes_status = 'failed', notes_error = 'Almanac stopped while writing them.' "
                    "where notes_status = 'writing'")
        con.execute("update recordings set notes_status = 'done', notes_error = 'Almanac stopped before making your change. Ask again.' "
                    "where notes_status = 'changing'")


def _view(con, r) -> dict:
    d = dict(r)
    d["transcript"] = json.loads(d["transcript"]) if d["transcript"] else None
    d["jottings"] = json.loads(d["jottings"]) if d["jottings"] else []
    pending = d.pop("pending")
    d["retry"] = d["status"] == "failed" and pending is not None  # a failed clean-up can run again
    d["label"] = _label(con, r)
    lk = lecture_kind(con, r["course_id"], r["date"])
    d["papers"] = lk["papers"] if lk and lk["kind"] == d["kind"] else []
    d["kind_name"] = KIND_NAMES.get(d["kind"] or "")
    v = con.execute("select why from note_versions where recording_id = ? order by id desc limit 1", (r["id"],)).fetchone()
    d["undo"] = v and v["why"]  # what Undo would take back
    return d


# ---- HTTP ---------------------------------------------------------------------

@router.get("/recordings/suggest")
def get_suggestion(request: Request):
    s = request.app.state
    out = suggest(s.db, s.clock)
    lk = lecture_kind(s.db, out["course_id"], out["date"]) if out["course_id"] is not None else None
    return {**out, "kind": lk and lk["kind"], "papers": lk["papers"] if lk else []}


@router.post("/recordings", status_code=202)
async def upload(file: UploadFile, background: BackgroundTasks, request: Request, course_id: int | None = None,
                 date: str | None = None):
    """A recording made elsewhere (the laptop's recorder, a phone voice memo, a Zoom download)."""
    s = request.app.state
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO:
        raise HTTPException(422, f"Can't read {ext or 'that'} files as a recording. Upload audio or video ({', '.join(sorted(AUDIO))}).")
    if course_id is not None and not s.db.execute("select 1 from courses where id = ?", (course_id,)).fetchone():
        raise HTTPException(404, "That course isn't in your plan.")
    now = local(s.clock.now())
    day = date or now.date().isoformat()
    with WRITE:
        src = s.db.execute("insert into sources (kind, title, text, status, created_at) values ('recording', ?, '', 'processing', ?)",
                           (file.filename, now.strftime("%Y-%m-%dT%H:%M"))).lastrowid
        rid = s.db.execute("insert into recordings (source_id, course_id, date, status, created_at) values (?, ?, ?, 'transcribing', ?)",
                           (src, course_id, day, now.strftime("%Y-%m-%dT%H:%M"))).lastrowid
    rec = s.db.execute("select * from recordings where id = ?", (rid,)).fetchone()
    lk = lecture_kind(s.db, course_id, day)
    with WRITE:
        s.db.execute("update sources set about = ? where id = ?", (_label(s.db, rec), src))
        s.db.execute("update recordings set kind = ? where id = ?", (lk and lk["kind"], rid))
    folder = s.db_path.parent / "recording-audio"
    folder.mkdir(exist_ok=True)
    audio = folder / f"{rid}{ext}"
    with open(audio, "wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    background.add_task(finalize, s.db, s.llm, s.clock, s.transcriber, rid, audio)
    return {"id": rid, "status": "transcribing"}


@router.post("/recordings/{id}/retry", status_code=202)
def retry(id: int, background: BackgroundTasks, request: Request):
    """Clean up again after a failed clean-up (the uncleaned text is still there; the audio isn't)."""
    s = request.app.state
    r = s.db.execute("select * from recordings where id = ?", (id,)).fetchone()
    if not r or r["status"] != "failed" or not r["pending"]:
        raise HTTPException(409, "Only a failed clean-up can be retried; a failed transcription needs the recording uploaded again.")
    _set(s.db, id, status="cleaning", error=None)

    def again():
        segments = json.loads(r["pending"])
        done = clean(s.llm, segments, vocabulary(s.db, r["course_id"]))
        _set(s.db, id, status="done", transcript=json.dumps(done), pending=None)
        with WRITE:
            s.db.execute("update sources set text = ?, status = 'done', error = null where id = ?",
                         ("\n".join(x["text"] for x in done), r["source_id"]))
        from . import lecture_notes
        lecture_notes.after_transcript(s.db, s.llm, s.clock, id)

    background.add_task(again)
    return {"id": id, "status": "cleaning"}


@router.get("/recordings")
def list_recordings(request: Request, course_id: int | None = None):
    con = request.app.state.db
    rows = con.execute("select * from recordings" + (" where course_id = ?" if course_id is not None else "")
                       + " order by date desc, id desc", (course_id,) if course_id is not None else ()).fetchall()
    return [_view(con, r) for r in rows]


@router.get("/recordings/{id}")
def get_recording(id: int, request: Request):
    con = request.app.state.db
    r = con.execute("select * from recordings where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return _view(con, r)


@router.post("/recordings/{id}/notes/retry", status_code=202)
def retry_notes(id: int, background: BackgroundTasks, request: Request):
    """Write the notes again (after a failure)."""
    s = request.app.state
    r = s.db.execute("select status, transcript from recordings where id = ?", (id,)).fetchone()
    if not r or r["status"] != "done" or not r["transcript"]:
        raise HTTPException(409, "Notes are written from the transcript, which isn't there.")
    from . import lecture_notes
    background.add_task(lecture_notes.after_transcript, s.db, s.llm, s.clock, id)
    return {"id": id, "notes_status": "writing"}


def _notes_free(con, id):
    from . import lecture_notes
    r = con.execute("select * from recordings where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    if r["notes_status"] in lecture_notes.BUSY:
        raise HTTPException(409, "The notes are being written or changed; try again when that's done.")
    return r


@router.put("/recordings/{id}/notes")
async def edit_notes(id: int, request: Request):
    """The student's own edit (the notes are theirs); Undo puts the old ones back."""
    from . import lecture_notes
    s = request.app.state
    _notes_free(s.db, id)
    notes = ((await request.json()).get("notes") or "").strip()
    lecture_notes.set_notes(s.db, s.clock, id, notes or None, "your edit")
    return _view(s.db, s.db.execute("select * from recordings where id = ?", (id,)).fetchone())


@router.post("/recordings/{id}/notes/change", status_code=202)
async def change_notes(id: int, background: BackgroundTasks, request: Request):
    """"Shorter", "add the derivation": the model makes the change, applied at once, with Undo."""
    from . import lecture_notes
    s = request.app.state
    r = _notes_free(s.db, id)
    ask = ((await request.json()).get("request") or "").strip()
    if not ask:
        raise HTTPException(422, "Say what to change.")
    if not r["notes"]:
        raise HTTPException(409, "This lecture has no notes yet.")
    _set(s.db, id, notes_status="changing", notes_error=None)
    background.add_task(lecture_notes.change_in_background, s.db, s.llm, s.clock, id, ask)
    return {"id": id, "notes_status": "changing"}


@router.post("/recordings/{id}/notes/undo")
def undo_notes(id: int, request: Request):
    from . import lecture_notes
    s = request.app.state
    _notes_free(s.db, id)
    if (why := lecture_notes.restore(s.db, id)) is None:
        raise HTTPException(409, "There's no change to undo.")
    return {**_view(s.db, s.db.execute("select * from recordings where id = ?", (id,)).fetchone()), "undone": why}


@router.delete("/recordings/{id}/transcript", status_code=204)
def delete_transcript(id: int, request: Request):
    """Only the text goes; the Recording (course, date, notes later) stays."""
    con = request.app.state.db
    if not con.execute("select 1 from recordings where id = ?", (id,)).fetchone():
        raise HTTPException(404)
    _set(con, id, transcript=None)
    with WRITE:
        con.execute("update sources set text = '' where id = (select source_id from recordings where id = ?)", (id,))



# ---- live: recording in the browser, Captions while it runs ----------------------
# The browser sends 16 kHz mono int16 audio in numbered pieces (about a second
# each); the PC appends them to a temporary file (deleted by the final pass)
# and a caption thread per Recording transcribes the newest audio about once a
# second. Every ~COMMIT seconds the oldest part is cut at a quiet moment and
# fixed as a caption line; the rest is shown as provisional. Captions are only
# for following along: Stop runs the final pass over the whole audio.

SR, WIDTH = 16000, 2
COMMIT = 10.0       # seconds of not-yet-fixed audio before a caption line is cut off
CUT_FROM = 6.0      # ...at the quietest moment after this many seconds
FRAME = 480         # samples per energy frame (30 ms)


class Live:
    def __init__(self, path: Path):
        self.path, self.lock, self.wake, self.stop = path, threading.Lock(), threading.Event(), threading.Event()
        self.next = None    # the piece number expected next (None: take the first one sent, e.g. after a restart)
        self.lines = []     # fixed caption lines {start, end, text}
        self.partial = ""   # the provisional text after them
        self.tail = 0       # bytes of audio already fixed as lines
        self.done = 0       # bytes the last caption covered
        self.error = None   # why captions aren't coming (the recording still goes on)
        self.loud_at = 0.0  # seconds into the audio of the last piece that wasn't silence
        self.heard = None   # when (clock time) the last piece arrived

    def state(self, since=0):
        size = self.path.stat().st_size if self.path.exists() else 0
        return {"next": self.next, "lines": self.lines[since:], "count": len(self.lines), "partial": self.partial,
                "seconds": round(size / (SR * WIDTH), 1), "captions_error": self.error}


def _audio_path(state, rid) -> Path:
    folder = state.db_path.parent / "recording-audio"
    folder.mkdir(exist_ok=True)
    return folder / f"{rid}.pcm"


def _live(state, rid) -> Live:
    """The running Recording's state, recreated after a restart (captions start over)."""
    if rid not in state.live:  # app.state.live: the running Recordings of this app
        state.live[rid] = Live(_audio_path(state, rid))
        threading.Thread(target=_captioner, args=(state.transcriber, state.live[rid]), daemon=True).start()
    return state.live[rid]


def _quiet_cut(pcm: bytes, lo: float, hi: float) -> int:
    """Byte offset of the quietest 30 ms frame between lo and hi seconds."""
    samples = array("h", pcm[: len(pcm) - len(pcm) % 2])
    first, last = int(lo * SR) // FRAME, int(hi * SR) // FRAME
    best, best_e = first, None
    for f in range(first, max(first + 1, last)):
        frame = samples[f * FRAME:(f + 1) * FRAME]
        e = sum(x * x for x in frame) / max(1, len(frame))
        if best_e is None or e < best_e:
            best, best_e = f, e
    return best * FRAME * WIDTH


def _caption_once(transcriber, live: Live):
    with open(live.path, "rb") as f:
        f.seek(live.tail)
        pcm = f.read()
    secs = len(pcm) / (SR * WIDTH)
    start = live.tail / (SR * WIDTH)
    if secs > COMMIT:
        cut = _quiet_cut(pcm, CUT_FROM, secs - 0.5)
        text = transcriber.window(pcm[:cut])
        with live.lock:
            if text:
                live.lines.append({"start": round(start, 2), "end": round(start + cut / (SR * WIDTH), 2), "text": text})
            live.tail += cut
        pcm = pcm[cut:]
    text = transcriber.window(pcm) if len(pcm) > SR * WIDTH // 2 else ""
    with live.lock:
        live.partial, live.done, live.error = text, live.tail + len(pcm), None


def _captioner(transcriber, live: Live):
    """Captions for one Recording until it stops. A failure (the speech worker
    starting or missing) is shown, and the audio keeps being saved."""
    while not live.stop.is_set():
        live.wake.wait(1.0)
        live.wake.clear()
        if live.stop.is_set() or not live.path.exists() or live.path.stat().st_size <= live.done:
            continue
        try:
            _caption_once(transcriber, live)
        except Exception as e:
            live.error = str(e) or type(e).__name__
            time.sleep(2)


AROUND = timedelta(minutes=15)  # a class is "on" from 15 minutes before it starts until it ends


def classes_now(con, clock, course_id=None) -> list[dict]:
    """Class meetings on now (one course's, or any): occurrences of timed events."""
    now = local(clock.now()).replace(tzinfo=None, second=0, microsecond=0)
    today = now.date().isoformat()
    events = [dict(r) for r in con.execute("select * from events where course_id is not null"
                                           + (" and course_id = ?" if course_id is not None else ""),
                                           (course_id,) if course_id is not None else ())]
    on = []
    for e in plan.occurrences(events, today, today):
        if len(e["start"]) > 10 and e["end"] and len(e["end"]) > 10:
            start, end = (datetime.fromisoformat(e["start"][:16]), datetime.fromisoformat(e["end"][:16]))
            if start - AROUND <= now <= end:
                on.append(e)
    return on


def suggest(con, clock) -> dict:
    """What Start proposes: the class happening now (device audio if it meets
    online, i.e. its place is a link), else a course whose "watch the recording"
    task is open (device audio: a replay), else nothing (the microphone)."""
    today = local(clock.now()).date().isoformat()
    for e in classes_now(con, clock):
        online = bool(re.search(r"https?://|zoom", e.get("location") or "", re.I))
        return {"course_id": e["course_id"], "source": "device" if online else "mic", "date": today,
                "why": f"{e['title']} is on now" + (" (online)" if online else "")}
    task = con.execute("select title, course_id from tasks where status = 'open' and course_id is not null and "
                       "(lower(title) like '%recording%' or lower(title) like '%replay%' or lower(title) like '%watch%') "
                       "order by coalesce(do_date, due, '9999'), id limit 1").fetchone()
    if task:
        return {"course_id": task["course_id"], "source": "device", "date": today, "why": f"“{task['title']}” is open"}
    return {"course_id": None, "source": "mic", "date": today, "why": None}


@router.post("/recordings/start", status_code=201)
async def start(request: Request):
    """A live Recording: the browser then sends its audio to /chunk."""
    s = request.app.state
    body = await request.json()
    course_id = body.get("course_id")
    if course_id is not None and not s.db.execute("select 1 from courses where id = ?", (course_id,)).fetchone():
        raise HTTPException(404, "That course isn't in your plan.")
    now = local(s.clock.now())
    day = body.get("date") or now.date().isoformat()
    kind = body.get("kind") or ((lk := lecture_kind(s.db, course_id, day)) and lk["kind"])
    if kind and kind not in KIND_NAMES:
        raise HTTPException(422, "Unknown lecture kind.")
    on = classes_now(s.db, s.clock, course_id) if course_id is not None else []
    ends_at = on[0]["end"][:16] if on else None  # recording the class as it happens: stop 15 min after it ends
    with WRITE:
        src = s.db.execute("insert into sources (kind, title, text, status, created_at) values ('recording', ?, '', 'processing', ?)",
                           ("Live recording", now.strftime("%Y-%m-%dT%H:%M"))).lastrowid
        rid = s.db.execute("insert into recordings (source_id, course_id, date, kind, status, created_at, ends_at) "
                           "values (?, ?, ?, ?, 'recording', ?, ?)",
                           (src, course_id, day, kind, now.strftime("%Y-%m-%dT%H:%M"), ends_at)).lastrowid
    rec = s.db.execute("select * from recordings where id = ?", (rid,)).fetchone()
    with WRITE:
        s.db.execute("update sources set about = ? where id = ?", (_label(s.db, rec), src))
    _audio_path(s, rid).touch()
    live = _live(s, rid)
    live.next = 0
    return _view(s.db, rec)


def _running(state, rid):
    r = state.db.execute("select status from recordings where id = ?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404)
    if r["status"] != "recording":
        raise HTTPException(409, "This recording has stopped.")


@router.post("/recordings/{id}/chunk")
async def chunk(id: int, seq: int, request: Request, since: int = 0):
    """One numbered piece of audio. A piece already received is ignored; a gap
    is refused with the number expected, so the browser sends what's missing."""
    s = request.app.state
    _running(s, id)
    live = _live(s, id)
    data = await request.body()
    if len(data) % WIDTH:
        raise HTTPException(422, "Audio must be 16-bit samples.")
    with live.lock:
        if live.next is None:
            live.next = seq  # after a restart: carry on from what the browser has
        if seq > live.next:
            raise HTTPException(409, {"next": live.next, "message": "A piece is missing; send from next."})
        quiet = False
        if seq == live.next:
            with open(live.path, "ab") as f:
                f.write(data)
            live.next += 1
            live.heard = s.clock.now()
            seconds = live.path.stat().st_size / (SR * WIDTH)
            if _loudness(data) > SILENT:
                live.loud_at = seconds
            quiet = seconds - live.loud_at >= QUIET_STOP
    live.wake.set()
    if seq == live.next - 1 and quiet:
        auto_stop(s, id, f"it was quiet for {QUIET_STOP // 60} minutes", trim_to=live.loud_at + 5)
        raise HTTPException(409, "This recording has stopped: it was quiet for 10 minutes.")
    return live.state(since)


@router.get("/recordings/{id}/live")
def live_state(id: int, request: Request, since: int = 0):
    """Captions so far (for another device reading along)."""
    s = request.app.state
    r = s.db.execute("select status from recordings where id = ?", (id,)).fetchone()
    if not r:
        raise HTTPException(404)
    if r["status"] != "recording":
        return {"stopped": True, "status": r["status"]}
    return _live(s, id).state(since)


@router.post("/recordings/{id}/stop", status_code=202)
def stop(id: int, background: BackgroundTasks, request: Request):
    """Stop: the audio so far goes to the final pass (and is then deleted)."""
    s = request.app.state
    _running(s, id)
    wav = _close(s, id)
    background.add_task(finalize, s.db, s.llm, s.clock, s.transcriber, id, wav)
    return {"id": id, "status": "transcribing"}


def _close(state, rid, trim_to=None) -> Path:
    """End a live Recording: its audio (up to `trim_to` seconds) becomes a WAV for the final pass."""
    live = state.live.pop(rid, None)
    if live:
        live.stop.set()
    pcm = _audio_path(state, rid)
    wav = pcm.with_suffix(".wav")
    left = None if trim_to is None else int(trim_to * SR) * WIDTH
    with open(pcm, "rb") as src, wave.open(str(wav), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(WIDTH)
        out.setframerate(SR)
        while (left is None or left > 0) and (block := src.read(1 << 20 if left is None else min(1 << 20, left))):
            out.writeframes(block)
            left = None if left is None else left - len(block)
    pcm.unlink(missing_ok=True)
    _set(state.db, rid, status="transcribing")
    return wav


# ---- stopping by itself ----------------------------------------------------------------
# A Recording stops after 10 minutes of silence in its audio (the silent end
# is trimmed), when no audio has arrived for 30 minutes (the laptop closed:
# longer than the silence rule, since a network outage also stops arrivals while
# the browser keeps the audio to resend), and 15 minutes after its class ends
# when it was started during the class. A notification says so.

SILENT = 250          # RMS of 16-bit samples below which a second counts as silence
QUIET_STOP = 600      # seconds of silence in the audio
NO_AUDIO_STOP = timedelta(minutes=30)
AFTER_CLASS = timedelta(minutes=15)


def _loudness(pcm: bytes) -> float:
    samples = array("h", pcm[: len(pcm) - len(pcm) % 2])
    step = max(1, len(samples) // 4000)  # a sample of the second is enough
    picked = samples[::step]
    return (sum(x * x for x in picked) / max(1, len(picked))) ** 0.5


def auto_stop(state, rid, why: str, trim_to=None):
    rec = state.db.execute("select * from recordings where id = ?", (rid,)).fetchone()
    if not rec or rec["status"] != "recording":
        return
    wav = _close(state, rid, trim_to)
    notify(state.db, state.clock, "recording", f"Stopped recording {_label(state.db, rec)}",
           f"I stopped it because {why}. The transcript is on its way.", f"#lecture/{rid}")
    threading.Thread(target=finalize, args=(state.db, state.llm, state.clock, state.transcriber, rid, wav), daemon=True).start()


def watch(state):
    """Every scheduler tick: stop Recordings whose audio stopped coming or whose class is over."""
    now = local(state.clock.now()).replace(tzinfo=None)
    for r in state.db.execute("select id, ends_at from recordings where status = 'recording'").fetchall():
        live = state.live.get(r["id"])
        heard = local(live.heard).replace(tzinfo=None) if live and live.heard else None
        if heard is None:  # after a restart: when the audio file last grew
            path = _audio_path(state, r["id"])
            heard = datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else now
        if now - heard >= NO_AUDIO_STOP:
            auto_stop(state, r["id"], "no audio arrived for 30 minutes")
        elif r["ends_at"] and now >= datetime.fromisoformat(r["ends_at"]) + AFTER_CLASS:
            auto_stop(state, r["id"], "the class ended 15 minutes ago")


# ---- keeping the PC awake while it's needed (Windows) ------------------------------------

_awake = threading.local()


def keep_awake(state):
    """Ask Windows not to sleep while a Recording runs or a class is on (the
    laptop reaches Almanac on this PC). Set from the scheduler's own thread,
    which Windows ties the request to; released when no longer needed."""
    import os
    if os.name != "nt" or type(state.clock).__name__ != "SystemClock":
        return
    need = bool(state.db.execute("select 1 from recordings where status = 'recording' limit 1").fetchone()) \
        or bool(classes_now(state.db, state.clock))
    if need != getattr(_awake, "on", False):
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if need else 0))
        _awake.on = need


# ---- Jottings: lines typed during a Recording, stamped with the moment in the lecture --------

def _jottings(con, rid) -> list:
    r = con.execute("select jottings from recordings where id = ?", (rid,)).fetchone()
    if not r:
        raise HTTPException(404)
    return json.loads(r["jottings"] or "[]")


@router.post("/recordings/{id}/jottings", status_code=201)
async def add_jotting(id: int, request: Request):
    """{"at": seconds into the lecture's audio (pauses excluded), "text": "" for a Mark, "key": the
    browser's id for it, so a retried save isn't added twice}."""
    s = request.app.state
    body = await request.json()
    at, text, key = body.get("at"), (body.get("text") or "").strip(), body.get("key")
    if not isinstance(at, (int, float)) or at < 0:
        raise HTTPException(422, "A jotting needs its moment in the lecture.")
    with WRITE:
        items = _jottings(s.db, id)
        hit = next((j for j in items if key and j.get("key") == key), None)
        if not hit:
            hit = {"id": max((j["id"] for j in items), default=0) + 1, "at": round(float(at), 1), "text": text[:2000], "key": key}
            items.append(hit)
            items.sort(key=lambda j: (j["at"], j["id"]))
            s.db.execute("update recordings set jottings = ? where id = ?", (json.dumps(items), id))
    return hit


@router.delete("/recordings/{id}/jottings/{jid}", status_code=204)
def delete_jotting(id: int, jid: int, request: Request):
    s = request.app.state
    with WRITE:
        items = [j for j in _jottings(s.db, id) if j["id"] != jid]
        s.db.execute("update recordings set jottings = ? where id = ?", (json.dumps(items), id))


WATCHERS.extend([watch, keep_awake])
