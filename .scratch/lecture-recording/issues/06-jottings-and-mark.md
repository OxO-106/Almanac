# 06: Jottings and Mark

**What to build:** On the Recording page the student types Jottings; each line is saved with its offset in the lecture (not wall-clock, so Pause doesn't skew it). A Mark key (and button) adds a bare Jotting. Jottings are saved as typed (they survive a reload) and kept with the Recording for the notes in phase 2.

**Blocked by:** 05

**Status:** done

- [x] Each Jotting lands at the Transcript segment being spoken when it was written
- [x] A reload mid-lecture keeps the Jottings and the Recording going
- [x] Mark works from the keyboard without leaving the Jottings box

## Comments

2026-10-02. The Record page's right column. A line is stamped with the moment its typing began (seconds of recorded audio, the same clock as the Transcript's segments, so Pause doesn't skew it); Enter on an empty line, or the Mark button, adds a bare Mark. Each is saved to the PC as it's added (`POST /api/recordings/{id}/jottings`, with a key so a retry isn't added twice), queued and retried if offline, and can be removed. They're on the Recording, so a reload keeps them (resume loads them), and the lecture page lists them. Checked in the browser during a live recording: typing began at 0:14 and Enter came at 0:17, stamped 0:14; a Mark at 0:21; both on the lecture page after Stop.
