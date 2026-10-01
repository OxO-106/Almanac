# 02: One gate for every change

**What to build:** Every change to the plan goes through one apply function that validates it and records undo: suggestions, answers that fill in accepted items, Rewind, Clear, planner and check-ins. No direct SQL writes to plan tables outside it.

**Blocked by:** 01

**Status:** needs-triage

- [ ] An answer that dates an accepted item is recorded as a proposal accepted on the spot, visible in the item's history
- [ ] Rewind undoes through the same records (no special cases)
- [ ] A test fails if any module writes to tasks/events/deadlines/projects/courses outside the gate
