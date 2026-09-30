Status: ready-for-agent

# Almanac v1 (desktop)

Covers build phases 1 (core) and 2 (rhythm and timers). Phases 3–5 (Canvas feed, iPhone PWA and push, Gmail and images) get their own specs.

## Problem Statement

I'm a UCLA grad student taking several courses (this quarter: CS 239 · Ding, CS 239 · Kim, CS 269 · Soatto) while also pursuing long-term goals like research positions and jobs. The information about what I have to do is scattered across syllabi, course websites and my own head. Calendars only hold things that already have a time. The hard part is everything that doesn't: when to finish a first read of the paper I present on Nov 5, when to start the outline, how to fit three courses' milestones into the same weeks without everything landing on the night before. I also lose track of long-term goals because nothing checks in on them. And any tool that guesses dates or merges two courses because they share a number is worse than none, because I can't trust it.

## Solution

Almanac is a personal assistant that runs on my PC, which I also use from my laptop over Tailscale. I talk to it in one continuous chat and upload syllabi and other documents. It extracts Events, Deadlines, Tasks, Projects and Goals, each backed by a quote from its Source. Anything it can't find stated becomes a Question to me, never a guess. Every change it wants to make arrives as a Proposal in an Inbox, and I accept, edit or reject it. For each Project it plans Milestones backward from the deadline using effort estimates. It spreads work across days within my Capacity and gives each Task both a due date and a do date. It then keeps me on track: a morning Briefing, Check-ins at 8pm and 11pm on do dates, a nightly Replan, timed Sessions that teach it how long my work really takes, and weekly, monthly and quarterly Overviews. My own calendar UI (Today, Chat, Inbox, Calendar, Projects/Goals, Memory, Archive) shows all of it.

## User Stories

### Capturing from documents

1. As a student, I want to upload a syllabus PDF, so that the assistant extracts its Events, Deadlines and deliverables without my retyping them.
2. As a student, I want to upload DOCX and plain-text files, so that syllabi in any common format work.
3. As a student, I want a document that fails to parse to show the real error, and a second parser to be tried, so that I'm never told something false (like "password-protected") about my file.
4. As a student, I want every extracted item to show the exact quote from the Source it came from, so that I can verify it in seconds.
5. As a student, I want items whose quote can't be found verbatim in the Source to be discarded, so that invented items never reach my Inbox.
6. As a student, I want each Course identified by course number and instructor, so that two different CS 239s are never merged.
7. As a student, when a new document mentions a course number I already have with a different instructor, I want a Question asking whether it's a new Course, so that the assistant confirms and doesn't assume.
8. As a student, I want week-based dates ("Week 5") resolved against the term calendar, so that provisional syllabi still land on the calendar.
9. As a student, I want dates resolved from week numbers or marked "provisional" in the Source to be labeled that way, so that I know which dates might move.
10. As a student, I want a deliverable with no stated due date to become a Question and not a guessed date, so that my plan contains only facts I can trust.
11. As a student, I want deliverables that depend on my choices (which paper I present, my team slot) to become Questions, so that the plan is built on my actual choices.
12. As a student, I want recurring class meetings (MW 4–5:50pm) extracted as recurring Events, so that my week view shows my classes.
13. As a student, I want a class meeting with no stated time to become a Question, so that the calendar never shows an invented time.
14. As a student, I want no-class days and holidays in the Source respected, so that no Event or do date lands on them without reason.
15. As a student, I want re-uploading an updated syllabus to produce Proposals only for what changed, so that I don't re-review everything.

### Chat

16. As a user, I want one continuous chat with the assistant, so that I can talk about my plans and life the way I'd text a human assistant.
17. As a user, I want to brain-dump in chat ("need to email Prof. X about research, also job apps before Thanksgiving"), so that the assistant turns it into Proposals.
18. As a user, I want the assistant to ask follow-up Questions in chat when something is ambiguous, so that it never fills gaps silently.
19. As a user, I want the chat to use my Memories and the relevant Projects as context, so that its answers reflect my situation.
20. As a user, I want older chat history summarized automatically, so that the conversation can go on for months without losing important context.
21. As a user, I want a "discuss" button on any Project or Goal that opens the chat focused on it, so that I can talk about one thing in depth.
22. As a user, I want to tell the assistant about progress in chat ("finished half the paper"), so that it proposes the matching updates.
23. As a user, I want replies streamed as they're generated, so that the chat feels responsive on a local model.

### Inbox and Proposals

24. As a user, I want every change the assistant wants to make to arrive as a Proposal in the Inbox, so that nothing changes without my approval.
25. As a user, I want to accept, edit then accept, or reject each Proposal, so that I stay in control.
26. As a user, I want to accept all Proposals from one Source at once, so that a clean syllabus doesn't take 30 clicks.
27. As a user, I want Questions in the Inbox with an answer field, so that answering one unblocks the items that depend on it.
28. As a user, I want answering a Question to trigger new Proposals built from my answer, so that my answer flows into the plan.
29. As a user, I want rejected Proposals remembered, so that the assistant doesn't propose the same thing again.
30. As a user, I want an Inbox count visible on every screen, so that I know when something is waiting.

### Goals, Projects, Tasks

31. As a user, I want Goals with a horizon and a "why", so that my long-term aims are part of the plan.
32. As a user, I want the assistant to make sure every active Goal has at least one live Project with a concrete next Task, so that long-term goals keep moving.
33. As a user, I want the assistant to propose the next Project when one under a Goal finishes, so that momentum continues.
34. As a user, I want each Task to have a due date and a do date, so that I know both when it's due and when I planned to work on it.
35. As a user, I want Tasks without any date (a Goal's next step) to still get a proposed do date, so that nothing sits unscheduled forever.
36. As a user, I want to tick Tasks off on any screen, so that tracking progress costs nothing.
37. As a user, I want to create, edit and delete Goals, Projects, Tasks, Events and Deadlines by hand, so that I can fix anything directly.
38. As a user on a team project, I want only my part tracked as Tasks, with the team deadline shown as a Deadline, so that my list reflects my work.
39. As a user on a team project, I want the assistant to ask what my part is at each team milestone, so that my Tasks match what I actually agreed to.

### Planning

40. As a student, I want each Project with a deadline planned backward into Milestones (e.g. first read, outline, draft, rehearse), so that big deliverables start early enough.
41. As a student, I want Milestones sized by effort estimates, so that the plan reflects how long things take.
42. As a student, I want no Milestone's do date within 2 days of a hard deadline unless I override it, so that the plan has slack.
43. As a student on a team, I want my part planned to finish 2 days before the team deadline, so that there's time to merge everyone's work.
44. As a student, when several Tasks have the same or nearby due dates, I want earlier do dates set for some of them, ranked by priority and ease, so that the week before doesn't collapse.
45. As a student, I want a soft Capacity (~6h weekdays, ~10h weekends) respected when do dates are placed, so that single days aren't overloaded.
46. As a student, I want a warning on days planned over Capacity, not a hard block, so that I can choose to push when I want to.
47. As a student, I want planning to avoid my class times and no-class days in its day-load math, so that Mon/Wed with four hours of class count as lighter days.
48. As a student, I want the plan presented as a Proposal with each Milestone's do date and estimate, so that I can adjust it before it's committed.
49. As a student, I want dates computed by code, not the model, so that "3 days before Nov 5" is always right.

### Slips and Replans

50. As a user, when I miss a Milestone's do date, I want a Replan Proposal for that Project's remaining Milestones, so that the plan stays realistic.
51. As a user, when the same Project slips a second time, I want the assistant to check in with me in chat, so that we talk about what's blocking me.
52. As a user, I want Replans to respect Capacity and the 2-day slack rule, so that catching up doesn't produce an impossible plan.

### Memory

53. As a user, I want a Memory page listing everything the assistant knows about me, so that nothing is stored invisibly.
54. As a user, I want new Memories proposed through the Inbox, so that I approve what it learns.
55. As a user, I want to edit and delete Memories, so that I can correct wrong ones.
56. As a user, I want my Capacity numbers on the Memory page, so that I can adjust them.
57. As a user, I want the assistant to suggest Capacity changes once Session data shows my real pace, so that the plan tracks reality.

### Timing and estimates

58. As a user, I want to start, pause and stop a timer on any Task from the PC or laptop, so that I record how long work actually takes.
59. As a user, I want one running timer at a time, so that Sessions don't overlap.
60. As a user, when a timer has run 2 hours, I want to be asked "still working on X?", with the Session capped if I don't answer, so that forgotten timers don't corrupt my data.
61. As a user, I want estimates computed per Work kind and unit (paper pages, slides, whole task), so that a 30-page paper isn't estimated like a 10-page one.
62. As a user, I want estimates to switch from the assistant's guess to my own data once a Work kind has 3+ Sessions, so that my plans get more accurate over time.
63. As a user, I want my estimate-vs-actual ratio per Work kind recorded as a Memory, so that I can see how I work.
64. As a user, I want to be asked for a paper's page count when it isn't known, so that per-page estimates work.

### Rhythm

65. As a user, I want a morning Briefing at 9am on the Today screen and as a notification with today's do dates, Events, Deadlines, open Questions and at-risk Milestones, so that I start each day knowing the plan.
66. As a user, I want a Check-in at 8pm on each Task's do date asking if it's done, so that progress gets recorded.
67. As a user, I want a second Check-in at 11pm only for Tasks still open, so that I'm not nagged about finished work.
68. As a user, I want a nightly Replan run at 10:30pm, before my PC usually shuts down around midnight, so that tomorrow's plan is ready.
69. As a user, when the PC was off during scheduled jobs, I want one catch-up summary on the next Briefing, not a burst of stale notifications, so that restarts are calm.
70. As a user, I want a weekly Overview every Sunday at 8pm (hours per Project and Goal, completed vs slipped, an honest one-line assessment, next week's do dates and Deadlines, Goals with no movement), so that I review my week.
71. As a user, I want a monthly Overview on the last day of each month at the same level plus per-Goal progress, never merged with the weekly one, so that I get both views.
72. As a user, I want a quarterly Overview at the end of each quarter recording what I did, grouped by Goal, so that I have a record.
73. As a user, I want all Overviews saved in an Archive, so that I can look back.
74. As a user, I want desktop notifications for Check-ins, Briefings and Overviews on the PC and the laptop, so that the assistant reaches me without my opening the app.

### Calendar and screens

75. As a user, I want Today as the home screen on every device, so that the most useful view is one click away.
76. As a user, I want a week view and a month view showing Events, Deadlines and Tasks on their do dates, so that I see my schedule at a glance.
77. As a user, I want each Course colored and labeled with number and instructor ("CS 239 · Kim"), so that I can tell same-number Courses apart.
78. As a user, I want to drag a Task to another day to change its do date, so that rescheduling is quick.
79. As a user, I want a Projects/Goals board showing each Goal's Projects and next Task, so that I see long-term progress.
80. As a user, I want provisional and unresolved items visibly marked in every view, so that I know which dates aren't firm.
81. As a user, I want the app to work well in a laptop browser window and in the installed Edge app, so that it feels like one app on both machines.

### Running it

82. As a user, I want Almanac started from the Start menu with a tray icon, like Papercut, so that it runs like a normal app.
83. As a user, I want Almanac reachable from my laptop over Tailscale at a private HTTPS address, so that I can use it away from the PC.
84. As a user, I want Almanac to reuse the Qwen model Papercut already has, so that nothing is downloaded twice and both apps can run at once without swapping models.
85. As a user, I want to switch the model in settings, so that I can upgrade later without code changes.
86. As a user, I want the app to tell me clearly when Ollama isn't running or the model is missing, so that I know why the assistant isn't answering.
87. As a user, I want my data backed up nightly, so that a bad write can't wipe my plan.

## Implementation Decisions

**Stack and runtime**
- Python 3.12, FastAPI, vanilla JS, same as Papercut. Its own virtual environment, its own server process on 127.0.0.1 port 8001 (Papercut uses 8000). Start-menu launcher, tray icon and start/stop scripts follow Papercut's pattern.
- Tailscale Serve exposes Almanac on the existing tailnet host on a separate HTTPS port.
- Data in one SQLite database inside the Almanac folder (location overridable by environment variable), with a nightly backup copy keeping the last 14.
- Time zone America/Los_Angeles. Plan times (do dates, due times, Event starts) are stored as local wall-clock strings so recurring classes keep their time across daylight saving; job bookkeeping uses UTC.

**LLM client module**
- Same interface as Papercut's client: chat with an optional JSON schema for structured output, a streaming variant, and a status check. Model and URL come from settings.
- Default model `qwen3.5:9b-q8_0` and the **same context size as Papercut (32768)**. Ollama reloads a model whenever the context size changes, so a mismatch would make the two apps fight over the GPU.
- The model never computes dates, never writes to the store, and never decides what's true without a quote. It returns structured candidates; code validates and resolves them.

**Ingest module** (Source → candidate items)
- Text extraction: PyMuPDF for PDF, a DOCX reader, plain text. On failure it tries the next extractor and records the actual error. It never infers a cause.
- The model returns candidates as structured data: kind (Event, Deadline, Task, Project, Course, Question), title, Course reference, date expression, and a verbatim quote.
- **Quote check:** after whitespace normalization, a candidate's quote must appear in the Source text. Otherwise the candidate is dropped and logged.
- **Date expressions** are structured, not free text: explicit date, explicit date and time, term week + weekday, recurring weekly pattern, relative-to-another-item, or unknown. Code resolves them against the term calendar. Unknown or choice-dependent dates become Questions.
- **Term calendar:** a settings record per quarter (instruction start, Week 1 Monday, holidays, finals). Fall 2026 is seeded from the UCLA registrar: instruction begins Thu Sep 24, so Week 1 starts Mon Sep 28. It can be edited.
- **Course identity** is number + instructor. A candidate that matches a number but not an instructor raises a Question.
- **Re-ingest** of a Source diffs against items previously accepted from it and proposes only additions, changes and removals.

**Proposal/Inbox module**
- One Proposal table covers every change type (create, update, delete, Replan, Memory, Question answer effects), with its Source reference and quote. Accepting a Proposal applies it in one transaction.
- Rejected Proposals are fingerprinted so equivalent ones are suppressed.
- Questions are Inbox entries that block their dependent candidates. Answering one re-runs the relevant extraction or planning step with the answer as a new Source.

**Plan store**
- Entities: Goal, Project, Task (due date, do date, Work kind, size in units, estimate, status, owner-is-me flag for team work), Event (one-off or recurring), Deadline, Course, Source, Proposal, Question, Memory, Session, ChatMessage, ChatSummary, Overview, Setting.
- Every entity extracted from a Source keeps its quote and a `provisional` flag.

**Planner module** (deterministic code, with the model only suggesting Milestone breakdowns)
- Input: a Project with a deadline, the model's suggested Milestone list (names, Work kinds, sizes), estimates, Capacity, the existing day loads, and class Events.
- It places Milestones backward from the deadline, with 2 days of slack before hard deadlines and 2 more for team merge. It spreads clustered due dates by moving do dates earlier, ranked by priority, then ease. It computes day load as planned estimates plus class time and flags days over Capacity.
- Output is always a Proposal.
- **Estimates:** a model guess until a Work kind has 3+ Sessions, then the user's median rate per unit.

**Chat agent module**
- The model gets: the system rules (no invention, quote requirement), Memories, the focused or relevant Projects, open Questions, the latest ChatSummary and recent messages. It answers in a structured envelope: reply text plus zero or more actions (propose item, propose Memory, ask Question, propose progress update). Actions become Proposals and Questions; the reply text streams.
- When history passes a token budget, older messages fold into a ChatSummary.

**Scheduler module**
- An in-process job runner that reads time from an injectable clock. Jobs: Briefing at 9:00am (built then and notified; if the PC was off at 9am, built on the next start), 8pm and 11pm Check-ins, 10:30pm nightly Replan, Sunday 8pm weekly Overview, last-day-of-month monthly Overview, end-of-quarter quarterly Overview, 2-hour timer prompt, nightly backup.
- Every job records its last run. On startup, missed runs are coalesced into one catch-up entry for the next Briefing; missed notifications are not sent.
- Notifications use the browser Notifications API from any open Almanac window (PC and laptop), plus a Windows toast from the tray on the PC.

**Web UI**
- Screens: Today (home), Chat, Inbox, Calendar (week and month), Projects/Goals, Memory, Archive.
- Each Course gets its own color. Provisional and unresolved items are marked. Tasks can be dragged to a new do date. A timer control appears on every Task.

## Testing Decisions

- **Good tests** exercise external behavior only: HTTP requests in, HTTP responses and later-observable state out. They don't assert on internal functions, tables or prompts.
- **Seam 1: the HTTP API.** Tests drive the FastAPI app in process, with two injected fakes. A **scripted LLM** returns canned structured outputs keyed by request. A **controllable clock** can be set and advanced. This covers:
  - ingest (quote check, date resolution, Course identity, Questions for missing facts, parser fallback)
  - Proposals and the Inbox
  - planning (backward placement, slack, clustering, Capacity warnings)
  - Replans after slips, Check-ins at 8pm and 11pm, catch-up after downtime
  - Overviews on their schedules, the 2-hour timer prompt, estimate switching after 3 Sessions
- **Seam 2: the extraction eval.** A script runs the real model over the documents in `seed/` and scores the output against hand-labeled expected items per Source: precision, recall, date accuracy, Questions raised for things that are genuinely unknown, and **zero tolerance for invented items**. This eval decides whether Qwen 3.5 9B is good enough or a larger model is worth trying. It is run by hand, not in the test suite.
- **Eval cases already known from `seed/`:**
  - Two different CS 239 Courses (Ding, MW 4–5:50; Kim, Tue/Thu, time not stated). Expect two Courses and a Question for Kim's meeting time.
  - Ding's final 6-page report has no due date. Expect a Question.
  - Kim's Nov 5 main-paper presentation depends on assignment. Expect a Question.
  - CS 269 is week-based and provisional. Expect provisional dates and a Question about oral final vs. project.
  - Kim's Nov 24/26 have no class.
- **Prior art:** Papercut has no automated tests. This is the first suite; it uses pytest with FastAPI's in-process test client.

## Out of Scope

- Canvas (Bruin Learn) calendar feed and periodic re-fetch: phase 3.
- iPhone PWA, Web Push through Apple, and a phone layout: phase 4.
- Gmail (g.ucla.edu) reading and image/screenshot input: phase 5.
- Time-blocking tasks into specific hours. Plans are at the Milestone/day level.
- Multiple users, sharing and sync with external calendars.
- Any cloud LLM.

## Further Notes

- **Open data Questions** the app should raise itself on the first ingest of `seed/`: Kim's presentation paper and team slot, Kim's class time, Ding's registered paper and project team, Ding's final report due date, CS 269 gating test status and final format.
- Planning and Check-ins assume the PC is on from morning until about 12am. Anything scheduled while it's off is caught up on the next start.
- Model upgrade path: once the eval exists, try a ~30B mixture-of-experts Qwen model at Q4 (partly offloaded to RAM) against the 9B. Switch only if the eval shows a clear gain. Note that the switch makes Papercut and Almanac load different models.
- Follow-up specs: phase 3 (Canvas), phase 4 (iPhone), phase 5 (Gmail and images).
