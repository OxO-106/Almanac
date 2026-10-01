# 01: Stable ids and origin

**What to build:** Ids are never reused, and every plan item knows where it came from. Migrate the plan tables, proposals, questions and sources to `autoincrement` ids (recreate and copy, keeping ids). Add `origin` to tasks, events, deadlines, projects and courses: source id, quote, and the proposal that created it.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Deleting the newest row and creating another never gives the old id
- [x] An accepted proposal's items carry its source, quote and proposal id
- [x] Existing data migrates in place (ids unchanged); a backup is taken first
- [x] Rewind and re-upload find items by origin, and refuse to touch a row whose origin doesn't match

## Comments

Built as a `history` table rather than origin columns: every change (create, update, delete) is logged with the proposal that made it and the values it replaced, so the first `create` entry is the item's origin and the rest is its trail. `plan.origin()` reads it; the editor shows it ("From CS259_F26_CourseInformation.pdf: …" / "Added by you"). Existing items were backfilled from accepted proposals. Ids: every table is `autoincrement`; the live database was migrated in place with ids kept and the counters started past any id a proposal ever created (backup: data/backups/before-stable-ids-20261001-1536.db).
