# Almanac

A local personal assistant that turns syllabi, documents and chat into goals, projects, tasks and a calendar, and keeps you on track. All AI runs on this PC through Ollama (shared with Papercut, `D:\Read\paper-reader`); Almanac uses `qwen3.5:35b-a3b` for chat and documents. Compare models with `scripts/chat_eval.py` before changing it. Spec: `.scratch/almanac-v1/spec.md`. Vocabulary: `CONTEXT.md`.

## Rules

- Never invent a fact. Anything not stated in a source (date, time, which paper, team split) becomes a Question to the user, not a guess.
- Every extracted item carries the source quote it came from.
- A course is identified by course number **and** instructor. Two courses can share a number.
- If a document fails to parse, report the real error and try the next parser; never guess the cause.
- Keep code minimal (ponytail style, `D:\Read\ponytail`). Don't re-download models; reuse the Ollama models Papercut already has.
- Every change to the plan goes through `plan.insert/change/remove` (they record history: origin, undo). Assistant changes are Proposals; a change the student's own answer settles uses `inbox.propose_and_accept`. `tests/test_gate.py` enforces it.
- Questions are created with a purpose and target (`inbox.ask`), worded in `asks.py`, answered in `questions.py`.
- Duplicates are judged by one rule, `merge.same`, for every reader.
- Syllabus and chat follow the rules in `.scratch/data-rules/spec.md`. Measure syllabus changes with `scripts/eval.py` against `seed/expected.json`.

## Agent skills

The engineering skills live in `D:\Read\mattpocock-skills\skills` (read each `SKILL.md` directly; they are not installed).

### Issue tracker

Local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles, label string = role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
