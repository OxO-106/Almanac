# 13: Scheduler, notifications and Briefing

**What to build:** An in-process job runner driven by the injectable clock records each job's last run and, on startup, coalesces missed runs into one catch-up entry. The 9:00am Briefing (today's do dates, Events, Deadlines, open Questions, at-risk Milestones, catch-up) is built, shown on Today and sent as a desktop notification from any open Almanac window, plus a Windows toast on the PC.

**Blocked by:** 04 (Inbox: Proposals and Questions)

**Status:** done

- [x] Job runner with last-run tracking and catch-up coalescing (no stale notification bursts)
- [x] Briefing at 9am; built on next start if the PC was off
- [x] Browser notifications on PC and laptop (tray toast on PC comes with ticket 17's tray icon)
- [x] API tests advancing the clock across 9am and across a simulated overnight shutdown
