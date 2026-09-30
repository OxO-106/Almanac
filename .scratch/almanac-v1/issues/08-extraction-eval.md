# 08: Extraction eval

**What to build:** A hand-run script runs the real model over the documents in seed/ and scores output against hand-labelled expected items: precision, recall, date accuracy, Questions raised for genuinely unknown facts, and invented items (must be zero). Output is a short report used to judge Qwen 3.5 9B vs a larger model.

**Blocked by:** 07 (Course identity and re-upload)

**Status:** ready-for-agent

- [ ] Hand-labelled expectations for the three seed syllabi, including: two CS 239 Courses; Kim meeting time Question; Ding final-report due date Question; Kim Nov 5 presentation assignment Question; CS 269 provisional weeks and final-format Question; Kim Nov 24/26 no class
- [ ] Report lists per-Source scores and every invented or missed item
- [ ] Model selectable from the command line to compare candidates

## Comments

**2026-09-30: baseline with qwen3.5:9b-q8_0** (`scripts/eval.py`, temperature 0, so runs are deterministic)

| Change | Required items with the right date | Questions | Unsupported dates | Noise |
|---|---|---|---|---|
| First version | 11/16 (68%) | 7/7 | 3 | 4 |
| + nearest date heading above schedule entries | 13/16 (81%) | 7/7 | 3 | 4 |
| + running headers/footers stripped, same-day duplicates merged | 13/16 (81%) | 6/7 | 1 | 6 |

The pipeline's checks hold (no invented date survives; every question a careful reader would ask is asked), but the 9B model's recall is unstable: a small change to the input text makes it find different items (Kim's tutorial appears, Ding's Oct 9/Oct 21/Nov 4 disappear). Next: compare qwen3.5:35b-a3b (24 GB download, needs the user's go-ahead).
