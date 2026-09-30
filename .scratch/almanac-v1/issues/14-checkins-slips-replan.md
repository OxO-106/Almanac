# 14: Check-ins, slips and nightly Replan

**What to build:** At 8pm on a Task's do date the assistant asks if it's done; at 11pm again only if still open. A missed Milestone produces a Replan Proposal for the Project's remaining Milestones; a second slip on the same Project triggers a chat check-in. The nightly Replan runs at 10:30pm.

**Blocked by:** 10 (Chat), 11 (Backward planner), 13 (Scheduler, notifications and Briefing)

**Status:** ready-for-agent

- [ ] 8pm and 11pm Check-ins, 11pm only for open Tasks
- [ ] Missed do date → Replan Proposal respecting slack and Capacity
- [ ] Second slip → chat check-in message
- [ ] Team Tasks check in on the user's part
- [ ] API tests driving the clock through 8pm, 10:30pm, 11pm
