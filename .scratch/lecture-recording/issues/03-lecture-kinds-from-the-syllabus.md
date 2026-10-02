# 03: Lecture kinds from the syllabus

**What to build:** The syllabus reader also records each course's usual Lecture kind (Paper session, Concept lecture, Presentation day) and, per schedule date, that lecture's kind and the papers listed for it (papers listed → Paper session; a project milestone or presentation → Presentation day). Nothing per course is hard-coded.

**Blocked by:** none

**Status:** done

- [x] The four real syllabi give (all but CS 259's usual kind; see Comments): CS 259, CS 239 Ding and CS 239 Kim usually Paper sessions; CS 269 Concept lectures; Ding's Oct 14 and Nov 30 Presentation days; Ding's Oct 5 a Paper session with its four papers
- [x] Added to `seed/expected.json` and checked by `scripts/eval.py`
- [x] A course with no schedule gets its usual kind only; a date with nothing listed falls back to it

## Comments

2026-10-02. Step 9 of the syllabus reader, `ingest._lecture_kinds`, into table `lecture_kinds` (per document: the usual kind with date null, and dates); looked up by `recordings.lecture_kind(course, day)`: that date, else a week holding it, else the usual kind. A Recording takes its kind on upload; the course's Lectures list and the lecture page show it (and a Paper session's papers).

Who decides what:
- **Usual kind**: the model (paper_session or concept_lecture only), kept only if its quote is in the document.
- **Papers per class**: code, from the readings the reader already found (Ding's listed papers, Kim's "[Required — Lecture N]"), including past ones, so a replayed lecture has its papers.
- **Presentation days**: code, from the schedule rows: a row naming a project, proposal, report or demo, with no papers and not "no class". A row with papers too counts only if the model names it and the row says what's presented (Ding's Nov 9 "First half Mid-term project report"; not Oct 21's "Proposal one-pager", which is handed in). The model alone was unreliable here: one run it missed Oct 14 and named Oct 21; it also called Kim's paper lectures presentation days (each has a student presenting).

Eval (real 35B, `scripts/eval.py`, now with lecture kinds), 2 runs: lecture kinds 18/20, required items 68/68, 0 wrong dates, 0 noise. The 2 misses are CS 259's usual kind: its half-page syllabus lists topics and graded short/long presentations, and the model reads it as lectures; the student says it's run as paper discussions. That's what Start's one-tap change (ticket 05) is for.

Found on the way and fixed: a "..." quote could skip into the next date's row ("Mon Nov 2 ... Mid-term project report", where the report is in the Wed Nov 4 row), so the first-half mid-term report was dated Nov 2 in two runs (it's Nov 9). `ingest.quoted` now keeps a "..." within one schedule row; the eval lists that date as known wrong.
