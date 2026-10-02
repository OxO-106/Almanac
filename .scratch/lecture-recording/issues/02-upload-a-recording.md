# 02: Upload a recording; the final pass makes a Transcript

**What to build:** Upload an audio file (phone voice memo, Zoom download, Sound Recorder or OBS file) as a Recording of a course's lecture. The final pass transcribes it with ticket 01, then the 35B cleans it in chunks: fillers, stutters and repeats out, broken sentences completed, the lecturer's words otherwise kept, terms corrected against the course vocabulary (paper titles, reading list, topics and terms from its syllabus). A word that matches nothing stays as heard; what's still uncertain is marked. Then the audio is deleted (ADR 0001). The Recording is a Source.

**Blocked by:** 01

**Status:** done

- [x] Upload accepts common audio and video (m4a, mp3, wav, webm, ogg, opus, flac, aac, mp4, mov, mkv), from the course page (so the course is known); the date is the file's date. Suggesting a course from an open "watch the recording" task moves to ticket 05's Start, where there's no course page
- [x] The Transcript keeps segment times; Jotting offsets (ticket 06) will land on it
- [x] Course vocabulary fixes names the transcriber mangles (test: "Kimmy linear" → "Kimi Linear" when Kimi Linear is on the reading list); an unmatched word is left alone
- [x] The audio file is gone from disk once the Transcript is saved, and also when the pass fails (the failure says what went wrong; the student re-uploads)
- [x] Progress and "Transcript ready" notifications, like document reading
- [x] Measured on a real lecture: a hand-checked passage, before and after clean-up

## Comments

2026-10-02. Built `app/recordings.py` (table `recordings`; a Recording is a Source of kind `recording`).

**The final pass:** Parakeet transcribes (ticket 01), the audio is deleted (also on failure, and any left by a crash is deleted at startup), the uncleaned segments are kept in `pending` only until clean-up is done (so a failed clean-up can run again without the audio), then the 35B cleans a chunk (about 2,500 characters, a few minutes of speech) at a time.

**Course vocabulary** (`vocabulary()`): the course, instructor and title; its plan items' titles (reading list papers without "Read"); and from the documents the course came from (found through where its items came from, not by label: the CS 259 syllabus never says "Instructor:", so its label has no name) the acronyms, CamelCase, words with digits, and names: capitalized mid-sentence and never written in lower case ("the Turing Award", not the heading "Grading").

**Guards found on the real lecture:**
- The model moves a few words across segment boundaries to finish sentences. Judging each segment alone threw away 4 segments' clean-up (14 "uh"s left); a chunk is now judged as a whole (it must keep at least half its words, so a summary is refused).
- The model swapped a nickname for the vocabulary name ("You can call me Mayu" → "Miodrag") in 6 of 6 runs, with either prompt wording. Code now lines up heard and cleaned words and marks `[?]` a course term written where nothing like it was heard nearby ("Potkonyak" → "Potkonjak" and "G Q A" → "GQA" are kept; "Miodrag [?]", and "Achievements [?]" which it inserted from the course title).

**On the 15.7 min CS 259 clip:** the final pass took 61 s (Parakeet about 10 s, the clean-up the rest); 0 fillers left; the instructor's name right; 2 doubtful terms marked, both genuinely not what was said; no false marks.

Example, before → after: "Uh first I will talk uh about uh course logistics. It will be twice per week on uh Monday and Wednesday at two PM for two hours." → "First, I will talk about course logistics. It will be twice per week, on Monday and Wednesday at 2 PM for two hours or slightly less."

2026-10-02, the student: a name heard as another name becoming the course's name ("Mayu" → "Miodrag") is fine, even good. Such swaps are no longer marked; only ordinary words turned into course terms, or terms added from nothing, are.
