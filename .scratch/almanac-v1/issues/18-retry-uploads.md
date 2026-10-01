# 18: Retry failed uploads

**What to build:** An upload that failed (model busy, parser error) can be retried from the Inbox without choosing the file again. Uploaded files are kept locally for this.

**Blocked by:** 05 (Upload documents)

**Status:** done

- [x] Uploaded files kept under data/uploads
- [x] Retry re-runs the reading on the same file
- [x] Retry button on failed uploads
- [x] API test: a failed upload retried succeeds
