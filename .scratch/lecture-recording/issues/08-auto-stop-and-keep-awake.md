# 08: Auto-stop and keeping the PC awake

**What to build:** A Recording stops by itself after 10 minutes of silence, and 15 minutes past the class's scheduled end when it's a class happening now; a notification says so, and silence at the end is trimmed. The PC is kept awake (Windows execution state, from the server) during scheduled class times and for an hour after a replay Recording starts, so the laptop can reach it.

**Blocked by:** 05

**Status:** done

- [x] Both stop rules, with the notification, tested with a fake clock
- [~] The PC doesn't sleep during a scheduled class: the Windows request is verified (see Comments); an actual night of sleeping/not sleeping hasn't been watched

## Comments

2026-10-02. Built in `app/recordings.py`.

**Stopping by itself:** 10 minutes of silence in the audio (RMS of 16-bit samples under 250; checked as each piece arrives), with the silence trimmed (audio kept to 5 s after the last sound); no audio arriving for 30 minutes (the laptop closed; longer than the silence rule on purpose: a network outage also stops arrivals while the browser keeps the audio to resend, and stopping then would lose it); and 15 minutes after its class ends when it was started during the class (`ends_at`, from `classes_now`, which Start's suggestion now shares). The last two are checked on every scheduler tick (`WATCHERS`). A notification says why; the page, if still open, stops capturing and opens the lecture.

**Keeping the PC awake:** on every tick (the scheduler's own thread, which Windows ties the request to), `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` while a Recording runs or a class is on (15 min before it until it ends), released after. Only on Windows and with the real clock. `powercfg /requests` needs an administrator, so the call was verified directly: the thread's state goes from 0x80000000 to 0x80000001 and back.

Tests: quiet for 5 s (patched from 10 min) stops with 3 s of sound + 5 s kept; 29 min without audio keeps waiting, 31 min stops; a class 10:00-11:00 recorded at 10:31 stops at the tick after 11:15 while audio still comes in.
