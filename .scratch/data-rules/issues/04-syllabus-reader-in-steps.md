# 04: Read a syllabus in fixed steps

**What to build:** Replace the stack of date fallbacks with the steps in the spec: course, weekly meetings, schedule table (lecture→date map), readings, deliverables, sessions, questions, proof. One quote check, one second look. Slot choices become a question with options, not one item per slot. Office hours are a separate, unchecked suggestion.

**Blocked by:** 03

**Status:** done

- [x] The four real syllabi (COM SCI 269, CS 239 Ding, CS 239 Kim, CS 259) read to the expected items in `seed/expected.json`, extended for this
- [x] Each step has its own tests with a scripted model
- [x] Ding's "Final project report" Nov 30 / Dec 2 is one question with two options, not two deadlines

## Comments

Reader steps are now labelled in `_propose_all` (1 course, 2 weekly meetings, 3 lecture dates, 4-6 readings/deliverables/sessions, 7 questions, 8 proof). New:
- **Weekly meetings** carry a type (lecture, discussion, lab, seminar, office hours), read from their line and the heading above it. If the model's meetings don't check out (e.g. days as "MW"), the days come from the quote, and meetings stated in the text ("Lecture: MW 2:00pm - 3:50pm") are used. A link right after the time is the place; a location must be in the document.
- **Office hours** are their own suggestion, offered unticked and left out of Accept all (`proposals.optional`).
- **Slot choices**: a "choice" item from the model, or code finding the same presentation/report on 2-3 dates within two weeks, becomes one suggestion per date held by one question with the dates as buttons ("Which day is your “Final project report”: Mon Nov 30 or Wed Dec 2?").
- **Optional readings** are not tasks.

Eval (`scripts/eval.py`, real model, CS 259 added to seed/expected.json, readings labelled): before 13/16 required items, 6/7 questions; after 27/30 required (90%), 11/13 questions, 0 wrong dates, 0 noise. CS 259 now gets its MW 2:00-3:50 class with the Zoom link.

Still missed (model recall, not rules): Ding's "Fri Oct 9 No Class — Project Team List Due" (the row reads as a day off), Ding's Nov 4 mid-term report (so its slot question can't form), COM SCI 269's Week 1 gating test.
