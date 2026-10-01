# 20: Canvas (Bruin Learn) calendar feed

**What to build:** The student pastes their Bruin Learn calendar feed link once (stored locally, never committed). Almanac fetches it every 3 hours: new assignments become Deadline proposals for the right Course, changed dates become updates, removed ones removal proposals. A section code (26F-COM SCI-239-LEC-4) is linked to a Course once, by asking when it's ambiguous. Assignments the syllabus already put in the plan are linked, not duplicated. A broken link is reported.

**Blocked by:** 07 (Course identity and re-upload), 13 (Scheduler)

**Status:** done

- [x] Feed link setting and Fetch now
- [x] ICS parsing (all-day and UTC due times to LA)
- [x] Section code to Course mapping, asked once when ambiguous (COM SCI = CS)
- [x] Diff by UID: create, update, removal proposals
- [x] Link to matching syllabus items instead of duplicating
- [x] Broken feed reported
- [x] API tests with a fake feed
