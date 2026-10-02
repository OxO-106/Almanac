# 10: Lecture notes, built on the Jottings, by Lecture kind

**What to build:** When a Transcript is ready, the 35B writes the lecture's notes. The student's Jottings are the outline: each kept word for word (shown as theirs), followed by what the lecturer was saying at that moment; a bare Mark becomes the point being made then. Topics they didn't jot are added. The shape follows the Lecture kind (spec): a Paper session per paper (the presenter's points: problem, method, results, limits; each question and its answer, by role; connections said in the room, and the assistant's own from the reading list, labelled "Almanac:"); a Concept lecture by concept (definitions, walk-throughs, examples); a Presentation day with feedback on the student's own work and a line on each other one. Notes keep everything important (length doesn't matter) and end with what was announced. Long lectures are written a part at a time, then combined.

**Blocked by:** 02, 03, 06

**Status:** done

- [x] Every Jotting appears in the notes word for word (checked by code; any the model dropped are added)
- [x] Paper-session notes name the day's papers from the reading list; classmates appear only by role
- [x] The assistant's own connections are marked "Almanac:"; nothing else in the notes goes beyond the Transcript
- [x] A 2-hour lecture fits (parts, then combined) and finishes in a few minutes
- [x] The lecture page shows the notes on top, the Jottings marked as the student's; "Notes ready" notification
- [x] Checked on a real transcript with the real model

## Comments

2026-10-02. `app/lecture_notes.py`, run after the Transcript (also after a retried clean-up; "Write again" if it fails).

**Writing:** one pass for up to 40 minutes of transcript (with times), else 40-minute parts then a combining pass; the prompt carries the course, date, the day's papers and (for a Paper session) the reading list, and the kind's shape (spec). "## Announced" ends the notes.

**What code guarantees (the model alone didn't, on the real lecture):**
- *Jottings.* The model, asked to put each jotting in place, left all three out in a single pass and, when combining parts, put the ✎ mark on lecture sentences and repeated whole sections. Now: a ✎ line that isn't one of the student's jottings loses the mark; any jotting (or Mark) left out is put just above the note point sharing the most words with what was said from 30 s before it to 15 s after; one nothing matches goes under "More of your jottings".
- *No guesses.* "(likely referring to touch interfaces …)" survived the instruction; parentheticals starting likely/probably/possibly/presumably/perhaps are removed.

**On the real CS 259 transcript (15.7 min, 1,540 words; 3 jottings at 1:55, a Mark at 2:50, 5:00):** notes in about 22 s, ~950 words in six topic sections; "office hours per request" above the office-hours point, the 5:00 question in the Turing Award section, the Mark above the point being made; "Announced" lists the office hours (week 2 or 3) and the week-2 Turing Award presentation. The first version (12-minute parts) said "Nothing announced", duplicated sections and invented ✎ lines: the 40-minute single pass and the rules above fixed those.

The lecture page shows the notes on top (✎ lines in amber, "Almanac:" labelled), the transcript folded under them.
