"""Recordings: a lecture's audio becomes a clean Transcript (see
.scratch/lecture-recording/spec.md and docs/adr/0001).

The final pass: the transcriber (Parakeet) turns the audio into timed
segments, the audio is deleted, then the model cleans the text a few segments
at a time (fillers, stutters and repeats out, broken sentences completed),
correcting names and terms against the course's vocabulary. The uncleaned
text is kept only until the clean-up is done."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile

from . import plan
from .clock import local
from .db import WRITE
from .scheduler import notify

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
        notify(con, clock, "recording", "Transcript ready", f"{label}: {round(seconds / 60)} min transcribed.",
               f"#lecture/{rec_id}")
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
    if folder.exists():
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
    with WRITE:
        con.execute("update recordings set status = 'failed', error = 'Almanac stopped while transcribing it. "
                    "Upload the recording again.' where status in ('transcribing', 'cleaning') and pending is null")
    for r in con.execute("select id from recordings where status = 'cleaning' and pending is not null").fetchall():
        _set(con, r["id"], status="failed", error="Almanac stopped while cleaning the transcript. Try again.")


def _view(con, r) -> dict:
    d = dict(r)
    d["transcript"] = json.loads(d["transcript"]) if d["transcript"] else None
    d["jottings"] = json.loads(d["jottings"]) if d["jottings"] else []
    pending = d.pop("pending")
    d["retry"] = d["status"] == "failed" and pending is not None  # a failed clean-up can run again
    d["label"] = _label(con, r)
    return d


# ---- HTTP ---------------------------------------------------------------------

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
    with WRITE:
        s.db.execute("update sources set about = ? where id = ?", (_label(s.db, rec), src))
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


@router.delete("/recordings/{id}/transcript", status_code=204)
def delete_transcript(id: int, request: Request):
    """Only the text goes; the Recording (course, date, notes later) stays."""
    con = request.app.state.db
    if not con.execute("select 1 from recordings where id = ?", (id,)).fetchone():
        raise HTTPException(404)
    _set(con, id, transcript=None)
    with WRITE:
        con.execute("update sources set text = '' where id = (select source_id from recordings where id = ?)", (id,))
