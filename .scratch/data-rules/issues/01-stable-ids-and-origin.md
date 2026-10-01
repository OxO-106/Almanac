# 01: Stable ids and origin

**What to build:** Ids are never reused, and every plan item knows where it came from. Migrate the plan tables, proposals, questions and sources to `autoincrement` ids (recreate and copy, keeping ids). Add `origin` to tasks, events, deadlines, projects and courses: source id, quote, and the proposal that created it.

**Blocked by:** None (can start immediately)

**Status:** needs-triage

- [ ] Deleting the newest row and creating another never gives the old id
- [ ] An accepted proposal's items carry its source, quote and proposal id
- [ ] Existing data migrates in place (ids unchanged); a backup is taken first
- [ ] Rewind and re-upload find items by origin, and refuse to touch a row whose origin doesn't match
