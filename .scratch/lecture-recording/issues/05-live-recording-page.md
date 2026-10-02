# 05: The live Recording page with Captions

**What to build:** A Record page. Start suggests the course (the class happening now, else one with an open "watch the recording" task), the Lecture kind (ticket 03) and the source (device audio for an online class or a replay, else the microphone), each one tap to change. Records the microphone (`getUserMedia`) or device audio (`getDisplayMedia` with audio), never both, and streams 16 kHz mono chunks over a WebSocket to the server, which feeds ticket 01's live mode and shows Captions about once a second. Pause and Stop; Stop runs ticket 02's final pass on the saved chunks.

**Blocked by:** 01, 02, 03

**Status:** ready-for-agent

- [ ] Works on the laptop over Tailscale (HTTPS) and on the PC, in Chrome/Edge, for the microphone and for a tab's or the screen's audio
- [ ] A short network drop loses no audio: chunks are buffered and resent; the Transcript has no gap
- [ ] Pause leaves the paused time out of the audio and the Transcript
- [ ] Layout: Captions on one side, the Jottings area on the other (ticket 06)
- [ ] Captions are visibly provisional; the Transcript replaces them after the final pass

## Comments
