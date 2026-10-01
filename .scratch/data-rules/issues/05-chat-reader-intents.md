# 05: Read chat as the student talking about their plan

**What to build:** Resolve references against the plan first (course by surname, nickname or number digits; items by title; "next class" from the weekly meeting), then act on one intent per action: add, add a routine (one series), change, done, remove, remember, answer, talk. Never ask what the plan already says.

**Blocked by:** 03

**Status:** done

- [x] "Move the one-pager to Tuesday" proposes changing that deadline, not a new one
- [x] "The CS 259 lecture is actually at 3" proposes changing the weekly event's time
- [x] "Watch the recording before the next class" makes one series, removable as one
- [x] "Delete the gating test" proposes removing it
- [x] Rewinding any of these undoes exactly that

## Comments

Chat actions gain `change` (new date, time, place/link, name) and `remove`. Items are matched by title (and course) against the plan; the model now sees the weekly classes and upcoming sessions/deadlines, so it can refer to them and needn't ask for dates the plan gives. A weekly class said again with a new time is a change, not a second class. New dates, times and places must be in the student's words (a place must also look like one, so "now" isn't). Removing one item of a routine removes the routine (the items its proposal created with the same name).

Real-model check (chat model, throwaway plan): "The CS 259 lecture is at 3pm now" → class 3:00–4:50; "Delete the gating test" → remove; "Move the one-pager to Tuesday" → Oct 6; "in Boelter 3400 from now on" → location; a new task still a new task; "thanks, that's all" → nothing.
