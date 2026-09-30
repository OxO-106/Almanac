# Almanac

A local personal assistant that turns syllabi, documents and chat into goals, projects, tasks and a calendar, and keeps you on track. All AI runs on this PC through Ollama, sharing Papercut's model (`D:\Read\paper-reader`). Spec: `.scratch/almanac-v1/spec.md`. Vocabulary: `CONTEXT.md`.

## Rules

- Never invent a fact. Anything not stated in a source (date, time, which paper, team split) becomes a Question to the user, not a guess.
- Every extracted item carries the source quote it came from.
- A course is identified by course number **and** instructor. Two courses can share a number.
- If a document fails to parse, report the real error and try the next parser; never guess the cause.
- Keep code minimal (ponytail style, `D:\Read\ponytail`). Don't re-download models; reuse the Ollama models Papercut already has.

## Agent skills

The engineering skills live in `D:\Read\mattpocock-skills\skills` (read each `SKILL.md` directly; they are not installed).

### Issue tracker

Local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles, label string = role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
