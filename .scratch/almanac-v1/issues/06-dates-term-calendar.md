# 06: Dates and term calendar

**What to build:** Date expressions are structured (explicit date, date+time, term week + weekday, weekly recurrence, relative, unknown) and resolved by code against an editable term calendar seeded with UCLA Fall 2026 (instruction starts Thu Sep 24; Week 1 = Mon Sep 28). Recurring class meetings become recurring Events. Week-based or source-marked-provisional items are flagged provisional. Unknown or choice-dependent dates become Questions. No-class days and holidays are respected.

**Blocked by:** 05 (Upload documents)

**Status:** done

- [x] Term calendar settings record, Fall 2026 seeded and editable
- [x] Code resolves every expression type; the model never computes dates
- [x] Recurring Events from weekly patterns; a meeting with no stated time raises a Question
- [x] Provisional flag set and shown
- [x] Missing due date → Question, never a guess
- [x] API tests for each expression type, Week 5 mapping, no-class day handling
