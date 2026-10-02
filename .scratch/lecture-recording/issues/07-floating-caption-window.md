# 07: Floating caption window

**What to build:** A "Float captions" button opens an always-on-top caption window (Document Picture-in-Picture, Chrome/Edge 116+) that the student can move and resize over the lecture video: the last two or three caption lines, large and readable. The student chooses per Recording between it and the Recording page.

**Blocked by:** 05

**Status:** done (laptop check pending: the student)

- [ ] (the student) The window stays above a browser video and Zoom on Windows
- [x] Closing it returns captions to the Recording page; the Recording keeps going
- [x] Where Document Picture-in-Picture isn't supported, the button isn't offered

## Comments

2026-10-02. "Float captions" on the Record page (only where `documentPictureInPicture` exists) opens a 620x150 window: dark, 22 px text, the last two caption lines and the provisional words in grey, updated with the page; "Captions here" (or closing the window) puts them back on the page, and the recording goes on. Stop closes it. If the browser refuses, the page says why. Checked in the preview: the pane can't open windows at all ("Internal error: no window", shown to the user as a message), so the window was stood in by a frame: styling, live text and closing all worked. A real Chrome/Edge window over a video or Zoom is the student's check on the laptop.
