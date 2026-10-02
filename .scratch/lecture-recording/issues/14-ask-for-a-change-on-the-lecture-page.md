# 14: Ask for a change to the notes on the lecture page

**What to build:** Under the notes, "Ask for a change" ("shorter", "add the derivation", "rewrite the GQA section as bullets"). The model gets the notes, the request and the Transcript (what was said, for "add …"), and returns only the sections it changed (new ones, removed ones), plus one sentence on what it did; code puts them in place, so untouched sections stay exactly as they were. Applied at once (kept version first, ticket 13), shown with Undo. The student's ✎ lines survive unless the request is about them; a line the model newly marks ✎ isn't theirs. A long Transcript is cut to the parts that match the request.

**Blocked by:** 13

**Status:** done

- [x] "Make the GQA section bullets" changes that section only; the others are byte for byte the same
- [x] A ✎ line the model dropped comes back; Undo restores the notes before the change
- [x] A failure leaves the notes as they were and says why

## Comments

2026-10-02. `lecture_notes.change`: CHANGE_PROMPT returns changed sections (replaces / before / markdown) and a summary; `apply_sections` swaps them in, so untouched sections stay byte for byte. Code then strips guesses, drops new lines that only say what the lecture didn't cover (that goes in the summary), and `restore_jottings` demotes ✎ lines the student didn't have and puts dropped ones back above the points they were above (skipped when the request is about jottings). A Transcript over 50k characters is cut to the windows that match the request. Runs in the background (notes_status "changing"), notification "Notes changed" with the summary; a failure leaves the notes and shows why. Real 35B on the CS 259 lecture: one section to 5 bullets 8 s, whole notes halved 16 s (872→527 words, all jottings kept), a summary at the top 6 s, "add … grading" said grading wasn't covered instead of writing it in.
