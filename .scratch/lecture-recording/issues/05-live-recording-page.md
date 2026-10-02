# 05: The live Recording page with Captions

**What to build:** A Record page. Start suggests the course (the class happening now, else one with an open "watch the recording" task), the Lecture kind (ticket 03) and the source (device audio for an online class or a replay, else the microphone), each one tap to change. Records the microphone (`getUserMedia`) or device audio (`getDisplayMedia` with audio), never both, and streams 16 kHz mono chunks over a WebSocket to the server, which feeds ticket 01's live mode and shows Captions about once a second. Pause and Stop; Stop runs ticket 02's final pass on the saved chunks.

**Blocked by:** 01, 02, 03

**Status:** done (laptop check pending: the student, on Chrome/Edge)

- [ ] (the student) Works on the laptop over Tailscale (HTTPS) and on the PC, in Chrome/Edge, for the microphone and for a tab's or the screen's audio
- [x] A short network drop loses no audio: chunks are buffered and resent; the Transcript has no gap
- [x] Pause leaves the paused time out of the audio and the Transcript
- [x] Layout: Captions on one side, the Jottings area on the other (ticket 06)
- [x] Captions are visibly provisional; the Transcript replaces them after the final pass

## Comments

2026-10-02. Built `web/record.js` (the Record page: sidebar, phone menu, and "Record a lecture" on a course page) and the live half of `app/recordings.py`.

**How it works.** Start suggests the course (`/api/recordings/suggest`: the class on now, device audio if its place is a link; else a course with an open "watch … recording" task, device audio; else the microphone) and the kind (ticket 03). The browser captures the microphone or a tab's/screen's audio (`getDisplayMedia`, "Share audio"), an AudioWorklet turns it into 16 kHz mono 16-bit pieces of one second, numbered, and POSTs them in order to `/api/recordings/{id}/chunk?seq=N`. The PC appends them to a temporary file; a repeat is ignored, a gap is refused with the number expected. Pieces the PC hasn't confirmed stay queued in the browser and are sent again. A caption thread per Recording (apart from the uploads, so the worker's start-up never holds audio) transcribes the not-yet-fixed tail about once a second; past 10 s it cuts at the quietest moment after 6 s and fixes that as a caption line; the rest is shown grey. If captions fail, the recording goes on and says why. Stop sends what's left, wraps the audio as WAV and runs ticket 02's final pass (the audio is then deleted). The screen is kept awake while recording; leaving the page asks first; after a reload the page offers to resume an open Recording (new audio, numbering continues) or stop it. A restart of the PC mid-lecture keeps the audio (`recover`). Running Recordings are per app (`app.state.live`).

**Checked in the browser with the real transcriber** (two minutes of the CS 259 lecture fed into the page's send queue at one second per second, since the preview pane can't grant microphone access): captions with timestamps and a grey provisional line; the first line about 35 s in on a cold start (the worker loading), then within a second or two; a 6 s network drop showed "Can't reach the PC: 7 s waiting, still recording" and afterwards the PC had all 66 s, in order; Pause kept 5 s out; Stop led to the lecture page with the final transcript and no audio left on disk; a reload offered to resume or stop the open recording; stopping an empty one said "No speech was found in the recording."

**Left for the student:** a real class on the laptop over Tailscale: the microphone, and a tab's audio with "Share audio" ticked, in Chrome or Edge.
