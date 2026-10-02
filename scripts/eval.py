"""Extraction eval: run the real model over seed/ and score it against the
hand labels in seed/expected.json.

    .venv\\Scripts\\python scripts\\eval.py [--model qwen3.5:9b-q8_0 (default: the document reader model)] [--runs 3] [--only "CS 239"]

A proposal is "supported" when a label matching its title gives its date.
Dated proposals that no label supports are listed as possible wrong dates:
the target is zero. Unlabelled proposals are listed as noise."""

import argparse
import io
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, ingest  # noqa: E402
from app.llm import DEFAULT_READER, Ollama  # noqa: E402


VERBOSE = False


class Clock:  # the eval always runs "on" Wed Sep 30 2026, 10:00 in Los Angeles
    def now(self):
        return datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc)


def has(text, spec):
    t = (text or "").lower()
    return all(any(alt.lower() in t for alt in part.split("|")) for part in spec.get("all", [])) and \
        all(any(alt.lower() in t for alt in part.split("|")) for part in spec.get("all2", [])) and \
        not any(w.lower() in t for w in spec.get("none", []))


def when_of(data):
    return data.get("window") or next((data[f][:10] for f in ("due", "start", "deadline") if data.get(f)), None)


def label_when(label):
    return label.get("window") or label.get("date")


def run_one(path: Path, labels: dict, llm) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        con = db.connect(Path(tmp) / "eval.db")
        cur = con.execute("insert into sources (kind, title, text, status, created_at) values "
                          "('document', ?, '', 'processing', '2026-09-30T10:00')", (path.name,))
        t0 = time.time()
        ingest.ingest(con, llm, Clock(), cur.lastrowid, path.name, path.read_bytes())
        secs = time.time() - t0
        src = dict(con.execute("select status, error, dropped from sources where id = ?", (cur.lastrowid,)).fetchone())
        props = [json.loads(r["ops"])[0] for r in con.execute("select ops from proposals order by id")]
        if VERBOSE:
            for r in con.execute("select ops, quote from proposals order by id"):
                d = json.loads(r["ops"])[0]["data"]
                print(f"      · {d.get('title') or d.get('number')} | {when_of(d)} | {r['quote']!r}")
            for d in json.loads(src_dropped := (con.execute("select dropped from sources").fetchone()[0] or "[]")):
                print(f"      × dropped {d['title']} | {d['quote']!r}")
        questions = [r["text"] for r in con.execute("select text from questions order by id")]
        kinds = [dict(r) for r in con.execute("select date, kind, papers from lecture_kinds order by id")]
        con.close()

    items = [p for p in props if p["op"] == "create" and p["kind"] in ("deadlines", "events", "tasks", "projects")
             and not p["data"].get("repeat")]
    labelled = labels["required"] + labels["allowed"]
    out = {"secs": round(secs), "status": src["status"], "error": src["error"],
           "dropped": len(json.loads(src["dropped"] or "[]")), "items": len(items), "questions_asked": len(questions)}

    # Required items: right date, wrong/missing date, or not found.
    out["required"] = []
    for lab in labels["required"]:
        hits = [p for p in items if has(p["data"]["title"], lab)]
        good = [p for p in hits if when_of(p["data"]) == label_when(lab)]
        out["required"].append({"label": lab["quote"], "ok": bool(good),
                                "got": sorted({str(when_of(p["data"])) for p in hits}) if not good else []})

    # Dated proposals no label supports: possible wrong dates.
    out["unsupported"] = []
    for p in items:
        w = when_of(p["data"])
        matching = [lab for lab in labelled if has(p["data"]["title"], lab)]
        if w and not any(label_when(lab) == w for lab in matching):
            out["unsupported"].append(f"{p['data']['title']} → {w}")
    for bad in labels["wrong_dates"]:
        for p in items:
            if has(p["data"]["title"], bad) and when_of(p["data"]) == bad["date"]:
                out["unsupported"].append(f"KNOWN WRONG: {p['data']['title']} → {bad['date']} ({bad['why']})")

    out["noise"] = [p["data"]["title"] for p in items if not any(has(p["data"]["title"], lab) for lab in labelled)]

    out["questions"] = [{"why": q["why"], "ok": any(has(text, q) for text in questions)} for q in labels["questions"]]

    courses = [p["data"] for p in props if p["op"] == "create" and p["kind"] == "courses"]
    out["courses"] = [{"want": f"{c['number']} · {c['instructor'] or '(not stated → ask)'}",
                       "ok": any(x["number"] == c["number"] and (c["instructor"] is None or x["instructor"] == c["instructor"])
                                 for x in courses)} for c in labels["courses"]]

    events = [p["data"] for p in props if p["op"] == "create" and p["kind"] == "events" and p["data"].get("repeat")]
    out["meetings"] = [{"want": f"{m['repeat']} {m['start']}-{m['end']}" + (f" at {m['location']}" if m.get("location") else ""),
                        "ok": any(e["repeat"] == m["repeat"] and e["start"][11:16] == m["start"]
                                  and (not m.get("location") or e.get("location") == m["location"]) for e in events)}
                       for m in labels["meetings"]]
    # Lecture kinds: the usual kind, and each labelled date's kind (exact date, else a week holding it, else usual) and papers.
    def kind_on(day):
        exact = [k for k in kinds if k["date"] == day]
        week = [k for k in kinds if k["date"] and "/" in k["date"] and k["date"][:10] <= day <= k["date"][-10:]]
        return (exact or week or [k for k in kinds if k["date"] is None] or [None])[0]
    lk = labels.get("lecture_kinds")
    out["kinds"] = []
    if lk:
        usual = next((k["kind"] for k in kinds if k["date"] is None), None)
        out["kinds"].append({"want": f"usually {lk['usual']}", "ok": usual == lk["usual"], "got": usual})
        for want in lk["dates"]:
            got = kind_on(want["date"])
            papers = " ".join(json.loads(got["papers"] or "[]")).lower() if got else ""
            ok = bool(got) and got["kind"] == want["kind"] and all(p in papers for p in want.get("papers", []))
            out["kinds"].append({"want": f"{want['date']} {want['kind']}" + (f" with {', '.join(want['papers'])}" if want.get("papers") else ""),
                                 "ok": ok, "got": got and f"{got['kind']} {papers[:80]}"})
    return out


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")  # ✓ / ✗ when written to a file on Windows
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--verbose", action="store_true", help="print every proposal with its quote")
    args = ap.parse_args()
    global VERBOSE
    VERBOSE = args.verbose
    llm = Ollama(lambda: {"ai": {"reader_model": args.model}} if args.model else {}, "reader_model", DEFAULT_READER)
    labels = json.loads((ROOT / "seed" / "expected.json").read_text(encoding="utf-8"))
    print(f"model: {llm.status()['model']}   runs: {args.runs}\n")

    totals = {"req": 0, "req_ok": 0, "unsupported": 0, "noise": 0, "q": 0, "q_ok": 0, "k": 0, "k_ok": 0, "secs": 0}
    for name, lab in labels.items():
        if name.startswith("_") or args.only.lower() not in name.lower():
            continue
        for run in range(args.runs):
            r = run_one(ROOT / "seed" / name, lab, llm)
            print(f"=== {name}  (run {run + 1}: {r['secs']}s, {r['status']}{', ' + r['error'] if r['error'] else ''})")
            print(f"    {r['items']} items, {r['questions_asked']} questions asked, {r['dropped']} dropped by the quote check")
            for c in r["courses"] + r["meetings"]:
                print(f"    {'✓' if c['ok'] else '✗'} {c['want']}")
            for x in r["required"]:
                print(f"    {'✓' if x['ok'] else '✗'} {x['label']}" + ("" if x["ok"] else f"   [got: {', '.join(x['got']) or 'nothing'}]"))
            for q in r["questions"]:
                print(f"    {'✓' if q['ok'] else '✗'} asks: {q['why']}")
            for k in r["kinds"]:
                print(f"    {'✓' if k['ok'] else '✗'} lecture kind: {k['want']}" + ("" if k["ok"] else f"   [got: {k['got'] or 'nothing'}]"))
            for u in r["unsupported"]:
                print(f"    ! date not supported by the labels: {u}")
            if r["noise"]:
                print(f"    ~ noise: {'; '.join(r['noise'])}")
            print()
            totals["req"] += len(r["required"])
            totals["req_ok"] += sum(x["ok"] for x in r["required"])
            totals["q"] += len(r["questions"])
            totals["q_ok"] += sum(q["ok"] for q in r["questions"])
            totals["k"] += len(r["kinds"])
            totals["k_ok"] += sum(k["ok"] for k in r["kinds"])
            totals["unsupported"] += len(r["unsupported"])
            totals["noise"] += len(r["noise"])
            totals["secs"] += r["secs"]
    t = totals
    if t["req"]:
        print(f"SUMMARY  required found with the right date: {t['req_ok']}/{t['req']} ({100 * t['req_ok'] // t['req']}%)   "
              f"questions asked: {t['q_ok']}/{t['q']}   lecture kinds: {t['k_ok']}/{t['k']}   unsupported dates: {t['unsupported']}   noise items: {t['noise']}   "
              f"time: {t['secs']}s")


if __name__ == "__main__":
    main()
