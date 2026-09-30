# 10: Chat

**What to build:** One continuous chat with streamed replies. The model answers in a structured envelope: reply text plus actions (propose item, propose Memory, ask Question, propose progress update) which become Proposals and Questions. Context includes rules, Memories, relevant Projects, open Questions and recent messages.

**Blocked by:** 04 (Inbox: Proposals and Questions), 09 (Memory page and Capacity)

**Status:** ready-for-agent

- [ ] Streaming chat endpoint and Chat screen
- [ ] Actions become Proposals/Questions, never direct writes
- [ ] Brain-dump message produces Proposals; ambiguity produces Questions
- [ ] Progress updates in chat become Proposals
- [ ] API tests with scripted LLM for each action type
