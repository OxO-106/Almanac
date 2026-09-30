# 05: Upload documents

**What to build:** The user uploads a PDF, DOCX or TXT. Text is extracted (falling back to the next extractor on failure, recording the real error). The model returns structured candidates, each with a verbatim quote; candidates whose quote is not found in the Source text are dropped and logged. Survivors become Proposals in the Inbox.

**Blocked by:** 04 (Inbox: Proposals and Questions)

**Status:** done

- [x] PDF via PyMuPDF, DOCX, TXT; failure shows the actual error, never a guessed cause
- [x] Structured extraction schema: kind, title, course ref, date expression, quote
- [x] Quote check after whitespace normalisation; failures dropped and logged
- [x] Each Proposal shows its quote and links to its Source
- [x] API tests with scripted LLM: invented-quote candidate dropped, parser fallback, happy path
