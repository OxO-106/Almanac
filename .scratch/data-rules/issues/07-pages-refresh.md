# 07: Open pages refresh when the plan changes

**What to build:** A change counter the server bumps on every applied change; open pages check it (with the existing poll) and re-render when it moves, unless the student is typing.

**Blocked by:** 02

**Status:** done

- [x] Accepting a suggestion on the phone shows on the open desktop calendar within a few seconds

## Comments

`GET /api/version` combines the newest history, proposal, question, chat, notification and source ids with the pending/open counts. Open pages check it every 5 s while visible (and when they become visible again) and redraw when it moves, never while typing, in a form, or with the editor open, keeping the scroll position. Verified live: a task added through the API appeared on the open Today page within seconds, and disappeared when deleted.
