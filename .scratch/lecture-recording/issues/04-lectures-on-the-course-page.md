# 04: Lectures list on the course page

**What to build:** Each course page lists its Recordings by date (newest first) with their kind. A lecture opens to its Transcript (notes come in phase 2), with a Delete transcript button, and its Proposals. Readable on the phone.

**Blocked by:** 02

**Status:** done

- [x] A Recording uploaded in ticket 02 shows under its course, dated (its kind comes with ticket 03)
- [x] Deleting a Transcript asks first and removes only the text
- [x] Works at phone width

## Comments

2026-10-02. The course page has a **Lectures** section (upload a recording, each lecture by date with its progress). `#lecture/<id>` shows the Transcript with timestamps; words marked `[?]` are underlined (dotted) with "Not sure this was heard right", per the spec's rule (marked, not asked). Delete transcript asks first; a failed clean-up offers "Clean up again". Lecture Proposals arrive with phase 2. Checked in the browser on the real CS 259 transcript, desktop and 375 px.
