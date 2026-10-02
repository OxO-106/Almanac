# 03: Lecture kinds from the syllabus

**What to build:** The syllabus reader also records each course's usual Lecture kind (Paper session, Concept lecture, Presentation day) and, per schedule date, that lecture's kind and the papers listed for it (papers listed → Paper session; a project milestone or presentation → Presentation day). Nothing per course is hard-coded.

**Blocked by:** none

**Status:** ready-for-agent

- [ ] The four real syllabi give: CS 259, CS 239 Ding and CS 239 Kim usually Paper sessions; CS 269 Concept lectures; Ding's Oct 14 and Nov 30 Presentation days; Ding's Oct 5 a Paper session with its four papers
- [ ] Added to `seed/expected.json` and checked by `scripts/eval.py`
- [ ] A course with no schedule gets its usual kind only; a date with nothing listed falls back to it

## Comments
