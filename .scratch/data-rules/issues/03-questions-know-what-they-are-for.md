# 03: Questions know what they are for

**What to build:** Each question is stored with its purpose (date of item X, choice among options, instructor of course X, Bruin Learn section, other) and the answer goes to one handler for that purpose. Replace `proposals.question_id`, `meta.fills` and `meta.type` with this. Questions with options show them as buttons. An "other" answer is read like a chat message, so it can still create or date an item.

**Blocked by:** 02

**Status:** needs-triage

- [ ] "October 21st" to "When must you submit the one-pager?" dates (or creates) the one-pager deadline
- [ ] "MW 2–3:50pm, Zoom link …" to "When is Lecture?" makes a weekly event with the link
- [ ] "Which slot (Mon Nov 30 or Wed Dec 2)?" shows both as buttons; the answer keeps that slot and drops the other
- [ ] All question wording comes from one place
