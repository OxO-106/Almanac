# 11: What the lecturer announces reaches the plan

**What to build:** From the Transcript, the 35B lists what the lecturer announced that changes the student's plan: a deadline set or moved, a reading assigned, an exam, a class cancelled or moved. Each needs a quote that's in the Transcript. A date relative to the lecture ("next Thursday") is read from the lecture's date. Something already in the plan with a different date becomes an update Proposal (the lecture wins over the syllabus: it's newer); something new becomes a Proposal; anything plan-relevant that isn't clear ("the fourteenth or so") becomes a question in chat with the quote, not a guess (spec Q10).

**Blocked by:** 02

**Status:** done

- [x] "The midterm report is now due the 13th" on a lecture of Nov 2, with "Midterm report due" on Nov 11 in the plan: a Proposal "Update … Nov 11 → Nov 13" quoting the lecture
- [x] "Read the Mamba paper for next Monday" on Wed Oct 7: a task due Sun Oct 11 (the day before the class), or Mon Oct 12 if no class is known
- [x] "Due the fourteenth or so": a chat question quoting it, no Proposal
- [x] A quote not in the Transcript is dropped
- [x] The lecture page lists the lecture's Proposals

## Comments

2026-10-02. `app/announcements.py`, run after the notes (a failure doesn't touch them); "From the lecture, for your plan" notification.

The model lists announcements (deadline, task, event, no_class) with quotes, a 40-minute chunk at a time; a quote not in the Transcript is dropped. Dates by code where the words allow (`ingest.said_when`), relative to the lecture's day; a day said without its month ("the 13th") is the next such day from the lecture: the real model filled in "October" for a November lecture, so a month the quote doesn't name is ignored. Existing item (same course, title sharing its words, any date) with another date → update Proposal, the lecture winning; a reading or prep for a class day → due the day before; an event without a time → a deadline-like marker; "no class" → that date skipped on the weekly class; unclear or undated → a chat question quoting "Prof. X said in the <date> lecture: “…”", purpose other (the answer is read like chat).

Real model, end to end on a made-up Nov 2 lecture with a Mon/Wed class and "Midterm report due" Nov 11 in the plan: Update Nov 11 → Nov 13; "Read Mamba paper" due Sun Nov 8 (for Mon Nov 9); no class Wed Nov 4; "due the fourteenth or so" → a question. On the real CS 259 lecture: office hours "in week two or week three" → one question (asked once though listed twice).

The lecture page has "For your plan": its Proposals (to Suggestions) and open questions (to Chat).
