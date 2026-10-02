# 15: Change notes from Chat, and undo from Chat

**What to build:** Chat knows the student's lectures with notes. "Make Monday's CS 259 notes shorter" is a "notes" action: the lecture is found by course and day (else the course's latest, else the latest of all), the change is made as in ticket 14, and Almanac says what it changed with a link to the notes. "Undo that" right after puts them back; Rewind on the message does too.

**Blocked by:** 14

**Status:** done

- [x] A chat request changes the right lecture's notes and the reply links to them
- [x] "undo that" and Rewind both restore the notes before the change

## Comments

2026-10-02. Chat's context lists the lectures with notes; a "notes" action finds the lecture (`chat._match_lecture`: course, then today/yesterday/a weekday/a date, else the latest) and runs `lecture_notes.change`; the reply says what changed with a link to the notes (chat markdown now renders [text](#page) links). "undo that" right after restores them (`_undo_notes`); Rewind does too (effects "notes"). Real 35B: "make the Nobel Prize part of Friday's CS 259 notes a short list of just the fields" changed that section in 10 s; "undo that" restored it exactly. Note: while a chat Question is waiting, a message answers it (existing behaviour), so a notes request then needs "Ask again later" first.
