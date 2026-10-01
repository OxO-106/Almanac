# 02: One gate for every change

**What to build:** Every change to the plan goes through one apply function that validates it and records undo: suggestions, answers that fill in accepted items, Rewind, Clear, planner and check-ins. No direct SQL writes to plan tables outside it.

**Blocked by:** 01

**Status:** done

- [x] An answer that dates an accepted item is recorded as a proposal accepted on the spot, visible in the item's history
- [x] Rewind undoes through the same records (no special cases)
- [x] A test fails if any module writes to tasks/events/deadlines/projects/courses outside the gate

## Comments

The gate is `plan.insert/change/remove` (with `by=proposal_id`), plus `plan.undo(proposal_id)`. `inbox.propose_and_accept` is used where the student's own answer settles a change to an accepted item. `tests/test_gate.py` fails if any module other than plan.py/db.py/dev.py writes to a plan table.
