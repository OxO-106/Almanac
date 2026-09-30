# 11: Backward planner

**What to build:** 'Plan this Project' asks the model for a Milestone breakdown (names, Work kinds, sizes) and code places Milestones backward from the deadline: estimates, 2-day slack before hard deadlines, 2-day team-merge buffer, earlier do dates for clustered due dates ranked by priority then ease, day load including class time, over-Capacity days flagged. Result is a Proposal.

**Blocked by:** 04 (Inbox: Proposals and Questions), 09 (Memory page and Capacity)

**Status:** done

- [x] Deterministic placement given candidates, estimates, Capacity and existing load
- [x] Slack and team buffer rules, overridable
- [x] Clustering spreads do dates earlier by priority then ease
- [x] Over-Capacity days warned, not blocked
- [x] Team Projects create Tasks only for the user's part
- [x] API tests with fixed clock for the Nov 5 presentation case and a clustered week
