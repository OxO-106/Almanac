# Almanac

A personal assistant that turns what the user uploads and says into a plan, and checks progress against it. It is one user's system, not a shared calendar.

## Plan structure

**Goal**:
A long-term outcome with a horizon (quarter, year, multi-year) and a stated why. Owns Projects.
_Avoid_: Objective, aspiration

**Project**:
A bounded piece of work toward a Goal, or standing alone (a course assignment). Owns Tasks; may end on a date or be open-ended.
_Avoid_: Assignment (as a type), epic

**Task**:
A unit of work the user does, with a due date and a do date.
_Avoid_: Todo, item, action

**Milestone**:
A Task produced by backward-planning a Project from its deadline ("first read of the paper by Oct 12").
_Avoid_: Step, checkpoint

**Event**:
Something that happens at a fixed time the user attends (lecture, presentation, office hours).
_Avoid_: Appointment, meeting

**Deadline**:
A moment by which something must be submitted or done, with no scheduled time around it.
_Avoid_: Due item

**Due date**:
When a Task must be finished.

**Do date**:
When the user plans to work on a Task. The assistant sets it; the user can move it.
_Avoid_: Scheduled date, start date

**Course**:
A class the user takes, identified by course number plus instructor. Two Courses may share a number.

## Assistant workflow

**Source**:
Anything the assistant extracts from: an uploaded document, a chat message, a calendar feed, an email.

**Proposal**:
A change the assistant wants to make (new Task, moved do date, new Memory, replan), with the Source quote that justifies it. Nothing changes until the user accepts.
_Avoid_: Suggestion, draft

**Inbox**:
The list of pending Proposals and Questions.

**Question**:
A specific thing the assistant needs the user to answer because no Source states it ("Which paper are you presenting?").
_Avoid_: Clarification, TBD

**Memory**:
A fact about the user the assistant keeps and uses (preferences, effort ratios, people). Visible and editable on the Memory page.
_Avoid_: Profile, note

**Replan**:
A Proposal that reschedules a Project's remaining Milestones after a slip or a change.

**Capacity**:
The user's soft limit on planned work per day (weekday and weekend hours).

**Session**:
A timed stretch of work on one Task.
_Avoid_: Time entry, log

**Work kind**:
The category a Task's effort is estimated by (reading a paper, making slides, other), with its unit (pages, slides, task).

## Rhythm

**Briefing**:
The morning summary of today's do dates, Events, Deadlines and at-risk Milestones.

**Check-in**:
The assistant asking whether a Task was done, at 8pm and (if still open) 11pm on its do date.

**Overview**:
A saved retrospective: weekly (Sunday 8pm), monthly (last day), quarterly (record of what was done). Never merged.
_Avoid_: Report, review
