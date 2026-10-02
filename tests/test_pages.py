"""Course websites: read from their address, with the sections they link to."""
from app import pages
from test_upload import item, items_reply

HOME = b"""<!doctype html><html><head><title>CS 239: LLMs for Code</title><script>var x = 1;</script></head><body>
<nav><a href="/">Home</a> <a href="schedule.html">Schedule</a> <a href="https://other.edu/syllabus">Their syllabus</a>
<a href="people.html">People</a></nav>
<h1>CS 239: Large Language Models for Code Intelligence</h1>
<p>Instructor: Robin Ding</p>
<p>Lectures: Mondays and Wednesdays, 4:00-5:50 p.m. <a href="https://ucla.zoom.us/j/123">Zoom link</a></p>
<p>Each student presents one paper from the reading list. Students are expected to read every paper before class and take part.</p>
</body></html>"""
SCHEDULE = b"""<html><head><title>Schedule</title></head><body><nav><a href="schedule.html">Schedule</a></nav><table>
<tr><th>Date</th><th>Topic</th><th>Due</th></tr>
<tr><td>Wed Oct 14</td><td>Course project proposal</td><td></td></tr>
<tr><td>Wed Oct 21</td><td>Distributed training</td><td>Proposal one-pager</td></tr>
</table></body></html>"""
SITE = {"https://cs239.example.edu/": ("text/html", HOME), "https://cs239.example.edu/schedule.html": ("text/html", SCHEDULE)}


def fake_fetch(site):
    def fetch(url):
        if url not in site:
            raise ValueError(f"{url} answered 404 Not Found.")
        kind, body = site[url]
        return url, kind, body
    return fetch


def test_a_page_reads_row_by_row_and_follows_the_course_sections(monkeypatch):
    monkeypatch.setattr(pages, "fetch", fake_fetch(SITE))
    title, text = pages.read_site("https://cs239.example.edu/", lambda pdf: "")
    assert title == "CS 239: LLMs for Code"
    assert "Wed Oct 21 | Distributed training | Proposal one-pager" in text  # one row per line
    assert "Zoom link (https://ucla.zoom.us/j/123)" in text  # a class link is kept: it's where the class is
    assert "=== Schedule (https://cs239.example.edu/schedule.html) ===" in text
    assert "var x" not in text and "People" not in text  # no scripts; the menu isn't content


def test_a_page_built_by_javascript_or_behind_a_sign_in_says_so(monkeypatch):
    monkeypatch.setattr(pages, "fetch", fake_fetch({"https://app.example.edu/": ("text/html", b"<html><body><div id=root></div></body></html>")}))
    try:
        pages.read_site("https://app.example.edu/", lambda pdf: "")
        raise AssertionError("expected an error")
    except ValueError as e:
        assert "JavaScript" in str(e) and "PDF" in str(e)
    try:
        pages.read_site("file:///C:/secret.txt", lambda pdf: "")
        raise AssertionError("expected an error")
    except ValueError as e:
        assert "isn't a web address" in str(e)


def test_a_website_is_read_like_a_syllabus_and_can_be_read_again(client, llm, monkeypatch):
    monkeypatch.setattr(pages, "fetch", fake_fetch(SITE))
    course = '{"courses": [{"number": "CS 239", "instructor": "Robin Ding", "quote": "Instructor: Robin Ding", "meetings": []}]}'
    proposal = item(kind="deadline", title="Course project proposal", quote="Wed Oct 14 Course project proposal",
                    when={"type": "date", "month": 10, "day": 14})
    llm.replies = [course, items_reply(proposal)]
    r = client.post("/api/uploads/url", json={"url": "https://cs239.example.edu/"})
    src = client.get(f"/api/sources/{r.json()['id']}").json()
    assert (src["status"], src["title"], src["url"]) == ("done", "CS 239: LLMs for Code", "https://cs239.example.edu/")
    assert "Course project proposal" in [p["summary"] for p in client.get("/api/inbox").json()["proposals"]]
    # the same address again is a new version of it
    llm.replies = [course, items_reply(proposal)]
    again = client.post("/api/uploads/url", json={"url": "https://cs239.example.edu/"}).json()
    assert client.get(f"/api/sources/{again['id']}").json()["lineage"] == src["id"]
    assert client.post("/api/uploads/url", json={"url": "not a site"}).status_code == 422


def test_a_site_that_cant_be_read_fails_with_what_it_answered_and_retries(client, llm, monkeypatch):
    monkeypatch.setattr(pages, "fetch", fake_fetch({}))
    r = client.post("/api/uploads/url", json={"url": "https://gone.example.edu/"})
    src = client.get(f"/api/sources/{r.json()['id']}").json()
    assert src["status"] == "failed" and "404 Not Found" in src["error"]
    monkeypatch.setattr(pages, "fetch", fake_fetch({"https://gone.example.edu/": SITE["https://cs239.example.edu/"]}))
    llm.replies = ['{"courses": []}', items_reply()]
    client.post(f"/api/sources/{src['id']}/retry")
    assert client.get(f"/api/sources/{src['id']}").json()["status"] == "done"
