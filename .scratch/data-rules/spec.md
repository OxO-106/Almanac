# Data rules: how the plan is built and kept

Status: built (2026-10-01). Tickets 01-07 are done; see each for what was measured.

## Why

The plan is written from five places (syllabus reading, chat, answers to
questions, Bruin Learn, the planner and check-ins), each with its own rules
grown one fix at a time. The result works for the cases we've hit, but it is
hard to predict and it has real bugs. The student noticed: a class added from
chat didn't appear, an answer with the date was ignored, a weekly lecture was
asked about as if it had no date.

This spec is the review, the rules we want instead, and the order to get there.

## What the review found

### Storage

1. **Ids are reused.** Tables use plain `integer primary key`, so SQLite hands
   out a deleted row's id again. Proposals remember the ids they created
   (`applied`), Rewind and re-uploads act on those ids, and Bruin Learn keeps
   `canvas_items.entity_id`. In the live database, proposals #39 and #43 both
   say they created deadline #7, which is now neither. Undoing #39 could have
   deleted an unrelated item.
2. **A plan item doesn't know where it came from.** Only the proposal knows
   (`applied`). Re-uploads, Rewind and "why is this here?" all have to search
   proposals backwards; items edited by hand or by an answer lose the trail.
3. **Questions have three hidden kinds of link**: `proposals.question_id`
   (blocks a suggestion), `questions.meta.fills` (dates an item without
   blocking it) and `questions.meta.type = canvas_section` (a special handler).
   A question with none of them (most questions from the questions pass)
   throws its answer away. Example: "October 21st" for the one-pager.
4. **Dates have three shapes with no field saying which**: an exact date or
   time, a week ("window" text plus the window's Monday in the date field), or
   none. Recurrence exists for events only (`repeat`, `until`, `skip` as a
   comma list); a task "after each class" becomes 17 unrelated rows.
5. **A suggestion can point at another suggestion** (`"course_id": "$p42.0"`),
   so items can't be accepted before their course, and it is easy to strand
   them (accepting one, rejecting the other).

### Writing

6. **Not everything goes through a proposal.** Answers write dates straight
   into accepted items (`chat._answer`), Rewind and Clear write directly, and
   hand fixes did too. Those writes skip validation (`plan._clean`) and leave
   no undo record.
7. **Duplicates are judged three ways.** Ingest has `_duplicate` (same kind,
   same day, half the title words), `merge.find` / `find_pending` look across
   the plan and the inbox, chat only skips repeats inside one message, Bruin
   Learn matches by its own uid first. A session and its deadline on the same
   day are never matched ("Mid-Project Check-in: Phase 1 Due" event and
   "Submit Phase 1 deliverables" deadline, Oct 29, are both on the calendar).

### Reading

8. **The syllabus reader is a stack of fallbacks.** A date can come from the
   model's report (`resolve`), the nearest date heading (`_repair`), the
   lecture table (`_before_lecture`), a lecture day shift, a row quote, a
   section quote, or the second look. Each was added for one case; together
   they are hard to reason about, and the course step had its own gaps (class
   times dropped when the instructor isn't named).
9. **Chat is read with syllabus rules where it shouldn't be, and without
   rules where it needs them.** It shares the quote check and date shapes,
   but a chat message is the student talking about *their* plan: it names
   courses loosely ("CS269", "Ding's class"), refers to existing things ("the
   report", "next class"), corrects ("actually it's at 3"), and states weekly
   habits ("I watch the recording instead"). Chat can only add; it can't
   change, move or remove an item, and it asks for things the schedule already
   gives ("what is the date of your next class?").
10. **Questions are written in eight places** (questions pass, item pass,
    "when is X due", "which day in week N", "who teaches", "what time does it
    meet", Bruin Learn section, chat), each with its own wording and its own
    link (see 3).

### Screens

11. Pages don't refresh when something changes elsewhere (accepting on the
    phone, a document finishing). The calendar showed no CS 259 class until
    reloaded.

## The rules

### One gate for every change

- Every change to the plan is a **Proposal**, applied by one function that
  validates it and records how to undo it. That includes answers that fill in
  an accepted item, Rewind, Clear, the planner and check-ins. An answer that
  fills something in is a proposal accepted on the spot, so it shows in the
  item's history and Rewind can undo it like anything else.
- Ids are never reused (`autoincrement`).
- Every plan item records its **origin**: the source, the quote, and the
  proposal that created it. A later change records its proposal too.

### Facts, choices and plans

Three kinds of information, each with one owner:

| Kind | Example | Owner |
|---|---|---|
| Course facts | "Lecture MW 2:00–3:50", "Proposal one-pager due Oct 21" | the syllabus (or Bruin Learn) |
| The student's choices | which paper, which team, which slot | the student, through questions or chat |
| The student's plans | "I'll watch the recording", "finish it by tomorrow" | the student, in chat |

A syllabus never decides a choice; chat may correct a fact ("the class moved
to 3") and that correction wins for this student.

### Reading a syllabus

The reader works in fixed steps, each with one rule.

1. **The course.** Number (department and number), instructor (only someone
   the document names as instructor or professor), title, term. Unknown
   instructor → ask "Who teaches …?"; everything else still proceeds.
2. **Weekly meetings.** Lecture, discussion, lab, seminar, office hours: days
   and times → one weekly event per meeting over the term's instruction weeks,
   skipping holidays and the document's no-class days; location or link if
   given. Office hours are offered as their own suggestion, unchecked by
   default.
3. **The schedule table.** Rows of "date (or Lecture N / Week N) → topic,
   readings, what's due". Used for three things only: the lecture→date map,
   readings, and deliverables listed in a row.
4. **Readings.** A required reading for a lecture → a task due the day before
   it. Optional readings (team-presentation choices) are not tasks.
5. **Deliverables**: anything that has the student produce or do something
   (submit, register, a report or proposal, a presentation or demo they give,
   a team list): a deadline at the stated date and time; only a week → a
   deadline over that week, and ask which day. The student's rule
   (2026-10-02), enforced in code by `ingest.deadline_or_event`.
6. **Sessions** they only attend (exam, tutorial, guest lecture, check-in,
   others' presentations): an event on its date. When students pick one of several slots → a question
   with those slots as options, not an event per slot.
7. **Questions.** Only dates and times: the day they present, a due date or
   class time the document leaves out. Never their topic, team or choice of
   option (2026-10-02). Merged per course, at most a handful.
8. **Proof.** Every item carries a quote checked against the text by one
   function (word for word, a schedule row, or one dated section). What fails
   gets one second look; what still fails is listed as left out, with the reason.

### Reading chat

Chat is read as the student talking about their own plan.

1. **Resolve references first**, against the plan: course by instructor
   surname (whole word), nickname or number digits ("CS269" = COM SCI 269);
   items by title ("the report"); "next class" from the course's weekly
   meeting; "tomorrow", weekdays, "end of the week" from today.
2. **Intents**, each with its own result:
   - *add* a task, deadline, event or weekly meeting
   - *add a routine* tied to a course ("watch the recording before the next
     class"): one series, shown and removed as one
   - *change* an existing item (move it, set its time, place or link, rename)
   - *done* / *not done*
   - *remove*
   - *remember* a fact about the student
   - *answer* the open question (see below)
   - talk: nothing changes
3. **Never ask what the plan already says** (the next class date, a course's
   instructor). Ask only when a needed fact is truly missing.
4. Every message logs its effects so Rewind undoes exactly them.

### Questions and answers

A question is created with **what it is for**:

| For | Answer handled as |
|---|---|
| a date of item X | a date, week day, or "MW 2–3:50" (weekly) for X |
| a choice among options | one of the options; shown as buttons |
| the instructor of course X | a name |
| the course of a Bruin Learn section | one of the courses |
| anything else | read like a chat message, so "October 21st" for "when is the one-pager due?" still creates or dates the item |

"Not yet" / "don't know" postpone any question (3 days if something waits on
it, else a week).

### Duplicates

One rule, used by every reader: the same **course**, a matching **date or
week**, and **titles that share half their words** mean the same thing, across
event and deadline when one says "due" and the other is the session that day.
What's new about it (time, place, course, project) is suggested as an update,
never as a second item.

### Screens

Open pages refresh when the plan changes (a lightweight change counter the
page checks, or the existing notification poll).

## Order of work

See `issues/`. Storage and the write gate come first because Rewind and
re-uploads depend on them; then questions; then the two readers; then
duplicates and screens.
