# 08: Auto-stop and keeping the PC awake

**What to build:** A Recording stops by itself after 10 minutes of silence, and 15 minutes past the class's scheduled end when it's a class happening now; a notification says so, and silence at the end is trimmed. The PC is kept awake (Windows execution state, from the server) during scheduled class times and for an hour after a replay Recording starts, so the laptop can reach it.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] Both stop rules, with the notification, tested with a fake clock
- [ ] The PC doesn't sleep during a scheduled class (checked on the real PC), and may sleep again afterwards

## Comments
