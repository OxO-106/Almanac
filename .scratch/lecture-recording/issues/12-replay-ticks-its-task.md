# 12: A replay ticks off its "watch the recording" task

**What to build:** When a Recording of a course finishes and that course has an open "watch … recording" task (e.g. made by "watch the recording after each class"), the task for that lecture (the earliest open one due on or after the lecture's date, else the most overdue) is marked done, as the student's own doing (`inbox.propose_and_accept`, so it can be undone), and the notification says so.

**Blocked by:** 02

**Status:** done

- [x] With "Watch the CS 269 recording" tasks due Oct 6 and Oct 8, a CS 269 recording of Oct 5 ticks the Oct 6 one only
- [x] It's in the item's history (undo works); a course without such a task is untouched

## Comments

2026-10-02. `lecture_notes.tick_replay_task`, after a Recording's notes: the course's open tasks whose title says watch/rewatch/recording/replay; the earliest due on or after the lecture's day, else the most overdue, is marked done through `inbox.propose_and_accept` (in its history; `inbox.withdraw` reverses it, as chat's Rewind does). Notification "Ticked off “…”", telling the student to reopen the task if they haven't watched it. Test: tasks due Oct 6 and Oct 8, a recording of Oct 5 ticks the Oct 6 one; a reading task of the same course is untouched; withdrawing reopens it.
