# 06: One duplicate rule

**What to build:** One matcher used by every reader: same course, matching date or week, titles sharing half their words, and a session and its deadline on the same day count as one ("Mid-Project Check-in: Phase 1 Due" and "Submit Phase 1 deliverables"). What's new is suggested as an update.

**Blocked by:** 01

**Status:** done

- [x] Uploading Kim's schedule after Bruin Learn has the Phase 1 deadline adds details, not a second item
- [x] The current live duplicates are found by a one-off check and offered for merging

## Comments

`merge.same()` is the one rule (course, date or week overlap, half the title words, same kind or a session + what's due at it). `merge.find`/`find_pending` (syllabus, chat, Bruin Learn) and ingest's within-document `_duplicate` use it; of a session and its deadline, the session is kept. `merge.duplicates()` / `offer_duplicates()` check the plan: on the live data it found exactly the Oct 29 pair and offered "Same thing twice: keep “Mid-Project Check-in: Phase 1 Due”, remove “Submit Phase 1 deliverables”".
