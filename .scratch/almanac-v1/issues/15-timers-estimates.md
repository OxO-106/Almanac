# 15: Timers and learned estimates

**What to build:** Start, pause and stop a timer on any Task from PC or laptop; one running at a time. After 2 hours the user is asked 'still working on X?' and the Session is capped if unanswered. Estimates per Work kind and unit switch from model guesses to the user's median rate after 3+ Sessions; the estimate-vs-actual ratio is proposed as a Memory. Unknown paper page counts become Questions.

**Blocked by:** 09 (Memory page and Capacity), 13 (Scheduler, notifications and Briefing)

**Status:** done

- [x] Session start/pause/stop, single running timer
- [x] 2-hour prompt and cap
- [x] Per-unit rates after 3 Sessions
- [x] Ratio Memory Proposal
- [x] API tests for the 2h prompt and the switch at the 3rd Session
