# 03: Questions know what they are for

**What to build:** Each question is stored with its purpose (date of item X, choice among options, instructor of course X, Bruin Learn section, other) and the answer goes to one handler for that purpose. Replace `proposals.question_id`, `meta.fills` and `meta.type` with this. Questions with options show them as buttons. An "other" answer is read like a chat message, so it can still create or date an item.

**Blocked by:** 02

**Status:** done

- [x] "October 21st" to "When must you submit the one-pager?" dates (or creates) the one-pager deadline
- [x] "MW 2–3:50pm, Zoom link …" to "When is Lecture?" makes a weekly event with the link
- [x] "Which slot (Mon Nov 30 or Wed Dec 2)?" shows both as buttons; the answer keeps that slot and drops the other
- [x] All question wording comes from one place

## Comments

Built in `app/questions.py` (handlers), `app/asks.py` (all wording) and `inbox.ask(purpose, target, options)`. Purposes: date, instructor, meeting, choice, section, other. A question can still hold suggestions up (`proposals.question_id`); `target` says what the answer acts on. `meta.fills` / `meta.type` were migrated into purpose/target (live DB backup: data/backups/before-question-purposes-20261001-1542.db). Choice options list what each option `adds`; what only unpicked options add is rejected (pending) or removed through the gate (accepted), and Rewind restores it.

The slot-question handler and buttons are built and tested; making the syllabus reader *produce* slot choices (instead of one item per slot) is part of 04.
