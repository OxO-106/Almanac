"""The student's papers, as Papercut (D:\\Read\\paper-reader) read them: read-only.
Lecture notes use them to say what each of a lecture's papers argues (also one
not presented in class) and to spell its terms right; the transcript cleaner
uses their topics as vocabulary. Almanac never writes to Papercut's library."""
import json
import math
import re
from collections import Counter
from pathlib import Path

from .config import PAPERCUT_LIBRARY

LIBRARY = PAPERCUT_LIBRARY  # tests point it elsewhere


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def library(root=None) -> list[dict]:
    """Every paper in Papercut's library: {"id", "title", "course", "paper" (its paper.json)}.
    A paper.json that can't be read (Papercut writing it, say) is skipped."""
    root = Path(root or LIBRARY)
    try:
        shelf = json.loads((root / "shelf.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        shelf = {}
    out = []
    for f in sorted((root / "papers").glob("*/paper.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": f.parent.name, "title": (p.get("meta") or {}).get("title") or "",
                    "course": (shelf.get(f.parent.name) or {}).get("course") or "", "paper": p})
    return out


def find(title: str, lib: list[dict]) -> dict | None:
    """The library's paper with this title: the same words, else one title
    starting with the other, else the same name before the colon ("GQA: …")."""
    want, head = _norm(title), _norm(title.split(":")[0])
    tests = [lambda t, h: t == want,
             lambda t, h: t.startswith(want) or want.startswith(t),
             lambda t, h: len(head) > 2 and h == head]
    for test in tests:
        for p in lib:
            if p["title"] and test(_norm(p["title"]), _norm(p["title"].split(":")[0])):
                return p
    return None


def short(p: dict) -> str:
    """A paper's short name: its title before the colon ("GQA")."""
    return p["title"].split(":")[0].strip()


def named(title: str, said: str) -> bool:
    """Whether a transcript names the paper: its name before the colon ("GQA",
    "Kimi Linear"), the first two words of a longer one ("Gated Delta"), or
    its initials ("NSA")."""
    words = _norm(title.split(":")[0]).split()
    forms = {" ".join(words), " ".join(words[:2])}
    if len(words) >= 3:
        forms.add("".join(w[0] for w in words))
    text = f" {_norm(said)} "
    return any(f and f" {f} " in text for f in forms)


_STOP = set("the a an and or of to in on for is are was were be it this that with as at by from you we they i he she "
            "so but if not have has had will would can could about what which who there their them our your how why "
            "does do did when then than its into just like also one".split())


def _terms(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 2 and w not in _STOP}


def passages(p: dict, query: str, k: int = 3) -> list[tuple[float, dict]]:
    """The paper's paragraphs sharing the most words with the query (rare words
    count more): (score, {"section", "text"}), best first. References left out."""
    paper, paras, section = p["paper"], [], ""
    sents = paper.get("sentences") or {}
    for b in paper.get("blocks") or []:
        if b.get("region") == "references":
            continue
        if b["type"] == "heading":
            section = b.get("text") or ""
        elif b["type"] in ("paragraph", "list_item"):
            text = " ".join(sents[x]["text"] for x in b.get("sentences") or [] if x in sents).strip()
            if text:
                paras.append({"section": section, "text": text[:1500]})
    words = [_terms(x["text"]) for x in paras]
    df = Counter(w for ws in words for w in ws)
    want = _terms(query)
    scored = [(sum(math.log(len(paras) / df[w]) for w in want & ws), x) for ws, x in zip(words, paras)]
    return [h for h in sorted(scored, key=lambda h: -h[0])[:k] if h[0] > 0]


def for_course(course, lib: list[dict]) -> list[dict]:
    """The papers Papercut files under this course ("CS 239 Ding"): number and instructor's surname."""
    surname = (course["instructor"] or "").split()[-1:] or [""]
    return [p for p in lib if course["number"] in p["course"] and surname[0] and surname[0] in p["course"]]


def _texts(items) -> list[str]:
    return [i["text"] if isinstance(i, dict) else str(i) for i in items or [] if i]


def abstract(paper: dict) -> str:
    """The paper's abstract, in its own words: the paragraphs under its "Abstract" heading."""
    out, on = [], False
    for b in paper.get("blocks") or []:
        if b["type"] in ("heading", "title"):
            if on:
                break
            on = _norm(b.get("text")).endswith("abstract")
        elif on and b["type"] == "paragraph":
            out.append(" ".join(paper["sentences"][s]["text"] for s in b.get("sentences") or [] if s in paper["sentences"]))
    return " ".join(out).strip()


def brief(p: dict) -> str:
    """What a lecture-notes writer needs to know about a paper: its abstract,
    Papercut's summary and its section headings."""
    paper, s = p["paper"], p["paper"].get("summary") or {}
    authors = s.get("authors")
    by = ", ".join(x for x in [", ".join(authors) if isinstance(authors, list) else authors, str(s.get("year") or ""), s.get("venue")] if x)
    lines = [f"Title in the student's library: {p['title']}"] + ([f"By: {by}"] if by else [])
    if a := abstract(paper):
        lines.append(f"Abstract (the paper's words): {a}")
    for key, name in [("tldr", "TL;DR"), ("problem", "Problem"), ("approach", "Approach")]:
        if s.get(key):
            lines.append(f"{name}: {s[key]}")
    for key, name in [("results", "Results"), ("contributions", "Contributions"), ("limitations", "Limitations")]:
        if items := _texts(s.get(key)):
            lines.append(f"{name}: " + " | ".join(items))
    if s.get("topics"):
        lines.append("Topics: " + "; ".join(s["topics"]))
    heads = [b["text"] for b in paper.get("blocks") or [] if b["type"] == "heading" and b.get("region") == "body"]
    if heads:
        lines.append("Sections: " + "; ".join(heads[:30]))
    return "\n".join(lines)


def vocabulary(course, lib: list[dict] | None = None) -> list[str]:
    """Titles and topics of the course's papers in Papercut."""
    papers = for_course(course, library() if lib is None else lib)
    return [t for p in papers for t in [p["title"]] + list((p["paper"].get("summary") or {}).get("topics") or [])]
