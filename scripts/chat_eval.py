"""How well a model reads chat messages into plan actions (chat.ACTIONS_PROMPT).

    python scripts/chat_eval.py [--model M] [--think] [--runs N]

Each case is a message the student might send, against a fixed plan, with a
check on the actions the model returns. Only the model's reading is scored
(not the code after it), so models and settings can be compared."""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from app.chat import ACTIONS_PROMPT, ACTIONS_SCHEMA  # noqa: E402
from app.llm import NUM_CTX  # noqa: E402

CONTEXT = """Today is Thursday, October 01, 2026, 23:00 in Los Angeles.

Coming up in the next two weeks:
- 2026-10-05T18:00: Reading group
- 2026-10-04: Read GQA: Training Generalized Multi-Query Transformer Models

Open tasks:
- Read GQA: Training Generalized Multi-Query Transformer Models
- Paper Presentation Registration

Weekly classes:
- CS 239 · Ding class meetings: MO,WE 16:00-17:50 (GEOLOGY 6704)
- CS 239 · Kim class meetings: TU 10:00-11:50
- CS 269 · Soatto class meetings: MO,WE 14:00-15:50

Planned sessions and deadlines:
- Reading group (2026-10-05T18:00)
- Midterm report due (2026-11-09)
- Course project proposal (2026-10-14)

Goals:
- none

What you know about the student:
- none"""


def kinds(acts):
    return [a.get("type") for a in acts]


def one(acts, kind):
    hits = [a for a in acts if a.get("type") == kind]
    return hits[0] if len(hits) == 1 else None


def when_is(a, *ok):
    w = (a or {}).get("when") or {}
    for o in ok:
        if all(w.get(k) == v for k, v in o.items()):
            return True
    return False


CASES = [
    ("I need to email Prof. Kim about my project idea by Friday",
     lambda acts: (a := one(acts, "task") or one(acts, "deadline")) and when_is(a, {"type": "weekday", "weekday": "FR"}, {"type": "date", "month": 10, "day": 2})),
    ("I want to go to the gym on Saturday morning",
     lambda acts: (a := one(acts, "event") or one(acts, "task")) and when_is(a, {"type": "weekday", "weekday": "SA"}, {"type": "date", "month": 10, "day": 3})
     and "memory" not in kinds(acts)),
    ("Ding's lecture got moved to 5pm",
     lambda acts: (a := one(acts, "change")) and "ding" in a["title"].lower() and a.get("start_time") == "17:00"),
    ("remind me to buy groceries tomorrow",
     lambda acts: (a := one(acts, "task")) and when_is(a, {"type": "in_days", "days": 1}, {"type": "date", "month": 10, "day": 2})),
    ("I finished the GQA reading",
     lambda acts: (a := one(acts, "progress")) and "gqa" in a["title"].lower()),
    ("Kim's class is Tuesdays and Thursdays 10 to 11:50",
     lambda acts: (a := one(acts, "event") or one(acts, "change")) and "TH" in (a.get("days") or "") and a.get("start_time") == "10:00"
     and a.get("end_time") == "11:50"),
    ("I have a dentist appointment next Wednesday at 3pm",
     lambda acts: (a := one(acts, "event")) and when_is(a, {"type": "weekday", "weekday": "WE"}, {"type": "date", "month": 10, "day": 7})
     and ((a.get("when") or {}).get("time") == "15:00" or a.get("start_time") == "15:00")),
    ("ugh I'm so tired today", lambda acts: acts == []),
    ("I want to get into a good PhD program by next year", lambda acts: one(acts, "goal") is not None),
    ("I prefer studying in the mornings", lambda acts: one(acts, "memory") is not None and len(acts) == 1),
    ("the midterm report for Ding is due Nov 11 instead",
     lambda acts: (a := one(acts, "change")) and when_is(a, {"type": "date", "month": 11, "day": 11})),
    ("I quit the reading group, cancel it",
     lambda acts: (a := one(acts, "remove")) and "reading group" in a["title"].lower()),
    ("I should watch the CS 269 recording after each class",
     lambda acts: (a := one(acts, "task")) and a.get("each_class") is True),
    ("I registered for my paper presentation already",
     lambda acts: (a := one(acts, "progress")) and "registration" in a["title"].lower()),
    ("Kim's class is actually on Thursday too, same time as Tuesday",
     lambda acts: (a := one(acts, "event") or one(acts, "change")) and "TH" in (a.get("days") or "")
     and a.get("start_time") == "10:00"),
    ("I need to prepare slides for my paper presentation, it's on Oct 19",
     lambda acts: any(when_is(a, {"type": "date", "month": 10, "day": 19}) for a in acts if a.get("type") in ("task", "event", "deadline"))),
    ("make the course project proposal a task",  # the kind itself is read by code from "a task"
     lambda acts: (a := one(acts, "change")) and "proposal" in a["title"].lower()),
    # requests for the assistant itself: done in the reply, nothing for the plan
    ("write me an email to the CS269 instructor requesting the recording of the last lecture", lambda acts: acts == []),
    ("what is the ReAct paper about?", lambda acts: acts == []),
    ("explain grouped-query attention to me like I'm new to it", lambda acts: acts == []),
    ("can you draft a message to my project team asking who takes which part", lambda acts: acts == []),
    ("help me write a reply to Prof. Kim saying I can't make office hours this week", lambda acts: acts == []),
    ("summarize what I have due in the next two weeks", lambda acts: acts == []),
    # ...and the close calls that are the student's own to-dos
    ("remind me to email Prof. Soatto about the recording tomorrow",
     lambda acts: (a := one(acts, "task")) and when_is(a, {"type": "in_days", "days": 1}, {"type": "date", "month": 10, "day": 2})),
    ("I have to write a summary of the CS 201 lecture by Monday",
     lambda acts: (a := one(acts, "task") or one(acts, "deadline")) and when_is(a, {"type": "weekday", "weekday": "MO"}, {"type": "date", "month": 10, "day": 5})),
    ("write me an email asking Kim for an extension, and remind me to send it Friday",
     lambda acts: len(acts) == 1 and (a := one(acts, "task")) and when_is(a, {"type": "weekday", "weekday": "FR"}, {"type": "date", "month": 10, "day": 2})),
    ("I need to email the TA my slides before Wednesday",
     lambda acts: (a := one(acts, "task") or one(acts, "deadline")) and when_is(a, {"type": "weekday", "weekday": "WE"}, {"type": "date", "month": 10, "day": 7})),
]


def ask(url, model, think, message):
    body = {"model": model, "stream": False, "think": think, "keep_alive": "30m", "format": ACTIONS_SCHEMA,
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 16000 if think else 4096, "presence_penalty": 0},
            "messages": [{"role": "system", "content": ACTIONS_PROMPT + "\n\n" + CONTEXT}, {"role": "user", "content": message}]}
    r = httpx.post(f"{url}/api/chat", json=body, timeout=600)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])["actions"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:9b-q8_0")
    ap.add_argument("--think", action="store_true")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    try:
        ask(args.url, args.model, args.think, "hi")  # load the model before timing
    except Exception:
        pass
    ok = total = 0
    secs = []
    for _ in range(args.runs):
        for message, check in CASES:
            t = time.time()
            try:
                acts = ask(args.url, args.model, args.think, message)
                good = bool(check(acts))
            except Exception as e:
                acts, good = f"ERROR {e}", False
            secs.append(time.time() - t)
            ok += good
            total += 1
            if not good or args.verbose:
                print(f"{'✓' if good else '✗'} {message}\n    {json.dumps(acts, ensure_ascii=False)[:400]}")
    secs.sort()
    print(f"\n{args.model} think={args.think}: {ok}/{total} right   median {secs[len(secs) // 2]:.1f}s   slowest {secs[-1]:.1f}s")


if __name__ == "__main__":
    main()
