"""Papercut's library, read-only: a lecture's papers found by title, what each says, the course's terms."""
import json

from app import papers


def shelve(root, pid, title, course="", summary=None):
    """A paper as Papercut stores it: paper.json with its blocks and summary, and its shelf entry."""
    d = root / "papers" / pid
    d.mkdir(parents=True)
    paper = {"meta": {"title": title},
             "blocks": [{"type": "heading", "text": "Abstract", "region": "body"},
                        {"type": "paragraph", "sentences": ["s1"], "region": "body"},
                        {"type": "heading", "text": "1 Introduction", "region": "body"},
                        {"type": "paragraph", "sentences": ["s2"], "region": "body"}],
             "sentences": {"s1": {"text": "We introduce grouped-query attention."}, "s2": {"text": "Decoding is slow."}},
             "summary": summary or {"tldr": "Share K/V heads per group.", "results": [{"text": "Close to MHA quality.", "highlights": []}],
                                    "authors": "J. Ainslie", "year": "2023", "topics": ["Grouped-query attention"]}}
    (d / "paper.json").write_text(json.dumps(paper), encoding="utf-8")
    shelf = root / "shelf.json"
    s = json.loads(shelf.read_text(encoding="utf-8")) if shelf.exists() else {}
    s[pid] = {"course": course} if course else {}
    shelf.write_text(json.dumps(s), encoding="utf-8")


def test_a_paper_is_found_by_its_title_whatever_the_case_or_length(papercut):
    shelve(papercut, "a1", "GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints")
    shelve(papercut, "b2", "KIMI LINEAR: AN EXPRESSIVE, EFFICIENT ATTENTION ARCHITECTURE")
    lib = papers.library()
    assert papers.find("Kimi Linear: An Expressive, Efficient Attention Architecture", lib)["id"] == "b2"
    assert papers.find("GQA: Training Generalized Multi-Query Transformer", lib)["id"] == "a1"  # the syllabus shortened it
    assert papers.find("GQA: grouped-query attention", lib)["id"] == "a1"  # the same name before the colon
    assert papers.find("Native Sparse Attention", lib) is None


def test_a_brief_has_the_abstract_summary_and_sections(papercut):
    shelve(papercut, "a1", "GQA: Training Generalized Multi-Query Transformer")
    brief = papers.brief(papers.library()[0])
    assert brief.splitlines() == ["Title in the student's library: GQA: Training Generalized Multi-Query Transformer",
                                  "By: J. Ainslie, 2023",
                                  "Abstract (the paper's words): We introduce grouped-query attention.",
                                  "TL;DR: Share K/V heads per group.",
                                  "Results: Close to MHA quality.",
                                  "Topics: Grouped-query attention",
                                  "Sections: Abstract; 1 Introduction"]


def test_the_course_vocabulary_is_its_papers_titles_and_topics(papercut):
    shelve(papercut, "a1", "GQA: Training", "CS 239 Ding")
    shelve(papercut, "b2", "SWE-agent", "CS 239 Kim")
    ding = {"number": "CS 239", "instructor": "Robin Ding"}
    assert papers.vocabulary(ding) == ["GQA: Training", "Grouped-query attention"]


def test_a_paper_papercut_is_writing_is_skipped(papercut):
    (papercut / "papers" / "x").mkdir()
    (papercut / "papers" / "x" / "paper.json").write_text("{half", encoding="utf-8")
    assert papers.library() == []
