# 13: Edit your notes yourself, with Undo

**What to build:** The lecture page's notes have an Edit button: the notes' markdown in a text box, Save and Cancel. Every change to a lecture's notes (by hand, a change request, chat) first keeps the version before it (`note_versions`: recording, notes, why, made_at), and the page offers **Undo** with what it undoes ("Undo: your edit"). Undo puts the previous version back; it can be pressed again for the one before that.

**Blocked by:** 10

**Status:** done

- [x] Saving an edit keeps the old notes; Undo brings them back; two edits undo in order
- [x] Notes being written or changed can't be edited at the same time (409)

## Comments

2026-10-02. `note_versions` keeps the notes before every change; `lecture_notes.set_notes` / `restore`. PUT /api/recordings/{id}/notes, POST .../notes/undo (409 when there's nothing); `undo` in the recording's view names what Undo takes back ("your edit", or the request in quotes). Edit/Save/Cancel on the lecture page; the page doesn't redraw while the editor is open. 409 while notes are being written or changed; a restart clears an interrupted change and says so.
