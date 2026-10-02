# 09: Read along on another device

**What to build:** While a Recording runs on the laptop or PC, opening it on the phone (or any other device) shows the live Captions and the Jottings, read-only.

**Blocked by:** 05

**Status:** done

- [x] Captions on the phone keep up with the recording device within a couple of seconds
- [x] The phone can't stop, pause or edit the Recording

## Comments

2026-10-02. While a Recording runs, Record on any other device offers "Follow along" (`#follow/<id>`): its Captions and provisional line, and its Jottings, polled every 1.5 s (`/api/recordings/{id}/live`), no controls. When it stops, the view says so and links to the lecture. Checked in two browser tabs, the follower at phone size: captions and a Jotting typed on the recorder showed up; the follower was about 1 s behind (0:41 vs 0:42); stopping on the recorder turned the follower into "This recording has stopped. Open the lecture."
