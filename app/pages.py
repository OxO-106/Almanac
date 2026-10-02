"""Course websites: a page, and the pages of the same site it links to for the
schedule, syllabus or readings, as one text for the syllabus reader.

Pages are read as the server sends them: a site that builds its content with
JavaScript, or that needs a sign-in (Bruin Learn), can't be read this way,
and the error says what came back."""
import re
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
import lxml.html

# Links worth following from the page given: a course site's other sections.
FOLLOW = re.compile(r"\b(schedule|syllabus|calendar|lectures?|readings?|papers|assignments?|homework|projects?"
                    r"|logistics|policies|exams?|info(rmation)?|overview)\b", re.I)
FOLLOW_PDF = re.compile(r"(syllabus|schedule|calendar|logistics|course[-_ ]?info)", re.I)
MAX_PAGES = 8
MAX_CHARS = 150_000
MIN_CHARS = 200  # less than this is a shell a script fills in, or an error page
SIGN_IN = re.compile(r"(log[-_]?in|sign[-_]?in|sso|shibboleth|cas/|auth)", re.I)
# A link whose address matters to the plan (the class's Zoom link is its location).
KEEP_HREF = re.compile(r"\b(zoom|meet|link|recording|stream|piazza|gradescope|campuswire|ed)\b", re.I)
BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "aside", "nav", "li", "ul", "ol", "dl", "dt", "dd",
         "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "thead", "tbody", "blockquote", "pre", "details", "summary",
         "figure", "figcaption", "hr", "form", "fieldset"}
DROP = ("script", "style", "noscript", "svg", "template", "iframe", "button", "select")
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Almanac/1.0 (reads a course page for its student)"


def fetch(url: str) -> tuple[str, str, bytes]:
    """(final url, content type, body). Errors say what the site answered."""
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": AGENT})
    except httpx.HTTPError as e:
        raise ValueError(f"Couldn't reach {url}: {type(e).__name__}: {e}")
    final = str(r.url)
    if r.status_code >= 400:
        raise ValueError(f"{url} answered {r.status_code} {r.reason_phrase}."
                         + (" The page needs a sign-in, which Almanac can't do: print it to PDF from your browser (Ctrl+P) and upload that."
                            if r.status_code in (401, 403) else ""))
    if final != url and SIGN_IN.search(urlparse(final).path + urlparse(final).netloc.split(".")[0]):
        raise ValueError(f"{url} sent me to a sign-in page ({final}), which Almanac can't use: "
                         "print the page to PDF from your browser (Ctrl+P) and upload that.")
    return final, r.headers.get("content-type", "").split(";")[0].strip().lower(), r.content


def html_text(data: bytes, base: str) -> tuple[str, str, list[tuple[str, str]]]:
    """(title, text, links) of an HTML page. Block elements and table rows start
    new lines, cells are separated by " | ", so a schedule reads row by row as in a PDF."""
    doc = lxml.html.fromstring(data)
    title = " ".join((doc.findtext(".//title") or "").split())
    href = lambda a: urldefrag(urljoin(base, a.get("href").strip()))[0]
    links = [(href(a), " ".join(a.text_content().split())) for a in doc.iter("a") if a.get("href")]
    # the site menu repeats on every page and is only links
    for bad in doc.xpath("|".join(f"//{t}" for t in DROP + ("nav", "head"))):
        bad.drop_tree()
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        if tag == "a" and el.get("href"):
            to, label = href(el), " ".join(el.text_content().split())
            if to.startswith("http") and KEEP_HREF.search(label) and to not in label:
                el.tail = f" ({to})" + (el.tail or "")
        if tag in BLOCK:
            el.text = "\n" + (el.text or "")
            el.tail = "\n" + (el.tail or "")
        elif tag in ("td", "th"):
            el.tail = " | " + (el.tail or "")
        elif tag == "br":
            el.tail = "\n" + (el.tail or "")
    lines = (re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"[ \t\xa0]+", " ", line)).strip(" |") for line in doc.text_content().splitlines())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return title, text, links


def _followed(start: str, links) -> list[str]:
    """Pages of the same course the start page links to for its sections: on the
    same site, under the start page's folder (not past offerings in an archive)."""
    s = urlparse(start)
    folder, out = s.path.rsplit("/", 1)[0] + "/", []
    for href, label in links:
        u = urlparse(href)
        if u.scheme not in ("http", "https") or u.netloc != s.netloc or not u.path.startswith(folder) \
                or href.rstrip("/") == start.rstrip("/") or href in out:
            continue
        name = u.path.rsplit("/", 1)[-1]
        if name.lower().endswith(".pdf"):  # lecture slides are PDFs too: only the syllabus or schedule
            if FOLLOW_PDF.search(label) or FOLLOW_PDF.search(name):
                out.append(href)
        elif FOLLOW.search(label) or FOLLOW.search(name):
            out.append(href)
    return out[:MAX_PAGES - 1]


def read_site(url: str, pdf_text) -> tuple[str, str]:
    """(title, text) of a course website: the page, then the linked sections.
    `pdf_text(bytes)` reads a linked PDF (a syllabus is often one)."""
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("That isn't a web address (it should start with http:// or https://).")
    final, kind, data = fetch(url)
    if kind == "application/pdf" or data[:5] == b"%PDF-":
        return final.rsplit("/", 1)[-1] or final, pdf_text(data)
    if "html" not in kind and not data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        raise ValueError(f"{url} isn't a web page or PDF (it's {kind or 'an unknown type'}).")
    title, text, links = html_text(data, final)
    if len(text) < MIN_CHARS:
        raise ValueError(f"{url} has only {len(text)} characters of text as the server sends it. If it shows more in a "
                         "browser, the site builds it with JavaScript: print it to PDF (Ctrl+P) and upload that.")
    parts = [text]
    for page in _followed(final, links):
        try:
            got, kind, data = fetch(page)
            if kind == "application/pdf" or data[:5] == b"%PDF-":
                name, body = page.rsplit("/", 1)[-1], pdf_text(data)
            else:
                name, body, _ = html_text(data, got)
        except Exception:
            continue  # a broken link on the site doesn't stop reading the rest
        if body.strip() and body.strip() not in "\n".join(parts):
            parts.append(f"=== {name or page} ({page}) ===\n{body}")
    return title or final, "\n\n".join(parts)[:MAX_CHARS]
