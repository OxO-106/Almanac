// Almanac. The assistant talks; the plan sits underneath.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const js = v => esc(JSON.stringify(v));  // a value inside an inline handler attribute
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
};
const send = (method, path, body) => api(path, { method, body: JSON.stringify(body) });
const detail = e => { try { return JSON.parse(e.message.replace(/^\d+ /, "")).detail; } catch { return e.message; } };

function toast(html) {
  const t = $("#toast");
  t.innerHTML = html;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.hidden = true, 7000);
}

const ICON = {
  undo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>',
  play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l13 8-13 8z"/></svg>',
  plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  clip: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.4 11.1l-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/></svg>',
  up: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  left: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>',
  right: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>',
  x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>',
  doc: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></svg>',
};

// ---- dates -------------------------------------------------------------------
// Plan times are Los Angeles wall-clock strings: "2026-10-05" or "2026-10-05T16:00".

const asDate = s => new Date(s.length === 10 ? s + "T12:00" : s);
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const monday = d => addDays(d, -((d.getDay() + 6) % 7));
const fmtDay = s => asDate(s).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
const fmtLong = s => asDate(s).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
const fmtTime = s => s && s.length > 10 ? asDate(s).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "";
const fmtWhen = (s, win) => win ? `week of ${fmtDay(win.slice(0, 10))}` : s ? fmtDay(s) + (s.length > 10 ? `, ${fmtTime(s)}` : "") : "";
const hours = s => s.length > 10 ? Number(s.slice(11, 13)) + Number(s.slice(14, 16)) / 60 : null;
const est = m => !m ? "" : m < 60 ? `${m} min` : `~${Math.round(m / 30) / 2} h`;
let todayIso = iso(new Date());

// ---- what the app knows ------------------------------------------------------

const PALETTE = ["#7C98B3", "#536B78", "#ACCBE1", "#637081", "#9DB4C8", "#3E525D", "#CEE5F2", "#8A9AA6"];
const TINTS = ["#DDEAF3", "#D9E1E6", "#E6F0F7", "#DEE2E7", "#E1EAF1", "#D7DEE2", "#EEF5FA", "#E3E7EA"];
let lookups = { courses: [], goals: [], projects: [], terms: [] };
const courseIdx = id => lookups.courses.findIndex(c => c.id === id);
const courseColor = id => courseIdx(id) < 0 ? "#C9D3DA" : PALETTE[courseIdx(id) % PALETTE.length];
const courseTint = id => courseIdx(id) < 0 ? "#EEF2F5" : TINTS[courseIdx(id) % TINTS.length];
const courseName = id => { const c = lookups.courses.find(c => c.id === id); return c ? `${c.number} · ${c.instructor.split(" ").pop()}` : ""; };
const courseTag = id => id ? `<span class="course"><i class="swatch" style="background:${courseColor(id)}"></i>${esc(courseName(id))}</span>` : "";

async function loadLookups() {
  const [courses, goals, projects, terms] = await Promise.all(["courses", "goals", "projects", "terms"].map(k => api(`/api/${k}`)));
  lookups = { courses, goals, projects, terms };
  const links = courses.map(c => `<a href="#course/${c.id}" data-view="course/${c.id}"><i class="swatch" style="background:${courseColor(c.id)}"></i><span>${esc(courseName(c.id))}</span></a>`).join("");
  $("#course-links").innerHTML = links || `<a href="#inbox"><span class="meta">Upload a syllabus to add one</span></a>`;
  $("#sheet-courses").innerHTML = links;
}

function termWeek(day) {
  const t = lookups.terms.find(t => t.starts <= day && day <= t.ends);
  if (!t) return "";
  const w = Math.floor((asDate(day) - asDate(t.week1)) / 864e5 / 7) + 1;
  return day > t.instruction_ends ? (day >= (t.finals_start || t.ends) ? "Finals" : "") : w >= 1 ? `Week ${w}` : "Week 0";
}

// ---- editing (the plan behind the conversation) --------------------------------

const KINDS = {
  goals: { one: "Goal", fields: [["title", "text", "Title"], ["why", "text", "Why it matters"], ["horizon", ["", "quarter", "year", "multi-year"], "Horizon"]] },
  projects: { one: "Project", fields: [["title", "text", "Title"], ["goal_id", "goals", "Goal"], ["course_id", "courses", "Course"],
    ["deadline", "datetime", "Deadline"], ["team", "check", "Team project"], ["notes", "area", "Notes"]] },
  tasks: { one: "Task", fields: [["title", "text", "Title"], ["project_id", "projects", "Project"], ["course_id", "courses", "Course"],
    ["due", "datetime", "Due"], ["do_date", "date", "Do it on"], ["work_kind", ["", "paper", "reading", "slides", "writing", "other"], "Kind of work"],
    ["size", "number", "Size (pages, slides…)"], ["notes", "area", "Notes"]] },
  events: { one: "Event", fields: [["title", "text", "Title"], ["course_id", "courses", "Course"], ["start", "datetime", "Starts"],
    ["end", "datetime", "Ends"], ["repeat", "days", "Repeats weekly on"], ["until", "date", "Until"], ["location", "text", "Where"]] },
  deadlines: { one: "Deadline", fields: [["title", "text", "Title"], ["course_id", "courses", "Course"], ["project_id", "projects", "Project"], ["due", "datetime", "Due"]] },
  courses: { one: "Course", fields: [["number", "text", "Number (e.g. CS 239)"], ["instructor", "text", "Instructor"], ["title", "text", "Title"]] },
  memories: { one: "Memory", fields: [["text", "area", "What to remember"], ["topic", "text", "Topic (e.g. work habits, people)"]] },
  terms: { one: "Term", fields: [["name", "text", "Name"], ["starts", "date", "Quarter begins"], ["instruction_begins", "date", "Instruction begins"],
    ["week1", "date", "Monday of Week 1"], ["instruction_ends", "date", "Instruction ends"], ["finals_start", "date", "Finals begin"],
    ["ends", "date", "Quarter ends"], ["holidays", "area", "Holidays (one per line: YYYY-MM-DD name)"]] },
};
const DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];

function input([name, type, label], v) {
  v = v ?? "";
  let el;
  if (Array.isArray(type)) el = `<select name="${name}">${type.map(o => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  else if (lookups[type]) el = `<select name="${name}" data-int><option value="">None</option>${lookups[type].map(o =>
    `<option value="${o.id}" ${o.id === v ? "selected" : ""}>${esc(o.title && type !== "courses" ? o.title : courseName(o.id))}</option>`).join("")}</select>`;
  else if (type === "area") el = `<textarea name="${name}" rows="3">${esc(v)}</textarea>`;
  else if (type === "check") return `<label class="check"><input type="checkbox" name="${name}" ${v ? "checked" : ""}> ${label}</label>`;
  else if (type === "days") el = `<span class="days">${DAYS.map(d => `<label><input type="checkbox" name="${name}" value="${d}" ${v.includes(d) ? "checked" : ""}>${d}</label>`).join("")}</span>`;
  else if (type === "datetime") el = `<span class="dt"><input type="date" name="${name}" value="${v.slice(0, 10)}"><input type="time" name="${name}__t" value="${v.slice(11, 16)}" aria-label="${label} time"></span>`;
  else el = `<input type="${type}" name="${name}" value="${esc(v)}" ${type === "number" ? 'step="any"' : ""}>`;
  return `<label>${label}${el}</label>`;
}

function readForm(root, kind) {  // root: a form or any element holding the inputs
  const out = {};
  for (const [name, type] of KINDS[kind].fields) {
    const el = root.querySelector(`[name="${name}"]`);
    if (!el) continue;
    if (type === "check") out[name] = el.checked;
    else if (type === "days") out[name] = $$(`[name=${name}]:checked`, root).map(c => c.value).join(",") || null;
    else if (type === "datetime") { const t = root.querySelector(`[name="${name}__t"]`).value; out[name] = el.value ? (t ? `${el.value}T${t}` : el.value) : null; }
    else if (type === "number") out[name] = el.value === "" ? null : Number(el.value);
    else if (el.dataset.int !== undefined) out[name] = el.value ? Number(el.value) : null;
    else out[name] = el.value || null;
  }
  return out;
}

async function openEditor(kind, item = null, preset = {}) {
  await loadLookups();
  const k = KINDS[kind], v = { ...preset, ...(item || {}) };
  const dlg = $("#editor");
  dlg.innerHTML = `<form method="dialog">
    <h2>${item ? "Edit" : "New"} ${k.one.toLowerCase()}</h2>
    ${item && "origin" in item ? `<p class="why">${item.origin
      ? `From ${esc(item.origin.source_kind === "chat" ? "what you said in chat" : item.origin.source || "a suggestion")}${item.origin.quote ? `: “${esc(item.origin.quote)}”` : ""}`
      : "Added by you."}</p>` : ""}
    ${k.fields.map(f => input(f, v[f[0]])).join("")}
    <p class="error" hidden></p>
    <div class="actions">
      ${item ? `<button type="button" class="btn quiet danger" data-act="delete">Delete</button>` : ""}
      <span class="grow"></span>
      <button type="button" class="btn" data-act="cancel">Cancel</button>
      <button class="btn primary">Save</button>
    </div></form>`;
  const form = $("form", dlg);
  form.addEventListener("click", async e => {
    const act = e.target.dataset.act;
    if (act === "cancel") dlg.close();
    if (act === "delete" && confirm(`Delete this ${k.one.toLowerCase()}?`)) { await api(`/api/${kind}/${item.id}`, { method: "DELETE" }); dlg.close(); render(); }
  });
  form.addEventListener("submit", async e => {
    e.preventDefault();
    try {
      await send(item ? "PATCH" : "POST", item ? `/api/${kind}/${item.id}` : `/api/${kind}`, readForm(form, kind));
      dlg.close(); render();
    } catch (err) { const p = $(".error", form); p.hidden = false; p.textContent = detail(err); }
  });
  dlg.showModal();
}

async function edit(kind, id) { openEditor(kind, await api(`/api/${kind}/${id}`)); }

async function toggleTask(id, done) {
  await send("PATCH", `/api/tasks/${id}`, { status: done ? "done" : "open" });
  render();
}

const taskItem = t => `<div class="item ${t.status === "done" ? "done" : ""}">
  <input type="checkbox" ${t.status === "done" ? "checked" : ""} onchange="toggleTask(${t.id}, this.checked)" aria-label="Done: ${esc(t.title)}">
  <a class="title" onclick='edit("tasks", ${t.id})'>${esc(t.title)}</a>
  ${courseTag(t.course_id)}
  <span class="est">${t.status === "done" ? "done" : esc(est(t.estimate_min))}</span>
  ${t.status === "done" ? "" : `<button class="play" onclick="startTimer(${t.id})" aria-label="Start a timer on ${esc(t.title)}">${ICON.play}</button>`}
</div>`;

// ---- the composer --------------------------------------------------------------

let pendingChat = null;  // a message typed on Today, sent once Chat opens
let sending = false;  // a chat message is on its way: its own renders keep the page current

const composer = (placeholder, onsubmit) => `<form class="composer" onsubmit="${onsubmit}">
  <label class="sr" for="say">Message Almanac</label>
  <textarea id="say" name="text" rows="1" placeholder="${esc(placeholder)}"
    onkeydown="if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.form.requestSubmit(); }"></textarea>
  <label class="icon-btn" title="Add a syllabus or document">${ICON.clip}<span class="sr">Add a syllabus or document</span>
    <input type="file" multiple accept=".pdf,.docx,.txt,.md" hidden onchange="uploadFiles(this.files)"></label>
  <button class="icon-btn send" aria-label="Send">${ICON.up}</button>
</form>`;

function sayFromToday(e) {
  e.preventDefault();
  const text = e.target.elements.text.value.trim();
  if (!text) return;
  pendingChat = text;
  location.hash = "#chat";
}

// ---- Today -------------------------------------------------------------------

let hiddenOffers = new Set();

async function answerQuestion(text) {
  if (!text?.trim()) return;
  await send("POST", "/api/chat", { text: text.trim() });
  render();
}
async function skipQuestion() { await api("/api/chat/skip", { method: "POST" }); render(); }

async function offer() {
  const [c, box] = await Promise.all([api("/api/chat"), api("/api/inbox")]);
  const ready = box.proposals.filter(p => !p.blocked_by && !p.optional && !hiddenOffers.has(p.id));
  if (c.current) {
    const more = ready.length ? `<p class="from waiting-line">${ready.length} suggestion${ready.length > 1 ? "s" : ""} from your documents ${ready.length > 1 ? "are" : "is"} waiting too. <a href="#inbox">Go through them</a></p>` : "";
    const q = c.current;
    const opts = q.options?.length
      ? q.options.map(o => `<button class="btn" onclick="answerQuestion(${js(o)})">${esc(o)}</button>`).join("")
      : "";
    return `<section class="offer" aria-label="A question">
      <p>${esc(q.text)}</p>
      ${opts ? `<div class="row-actions">${opts}<button class="btn quiet" onclick="skipQuestion()">Ask again later</button></div>`
             : `<form onsubmit="event.preventDefault(); answerQuestion(this.elements.a.value)"><label class="sr" for="qa">Your answer</label>
                  <input id="qa" name="a" placeholder="Your answer" autocomplete="off"><button class="btn primary">Answer</button>
                  <button type="button" class="btn quiet" onclick="skipQuestion()">Later</button></form>`}
      ${c.waiting ? `<span class="from">${c.waiting} more after this one, in <a href="#chat">Chat</a>.</span>` : ""}
    </section>${more}`;
  }
  if (!ready.length) return "";
  const p = ready[0];
  inboxCache = box.proposals;
  return `<section class="offer" aria-label="A suggestion">
    <p>Shall I add this? <strong style="font-weight:500">${esc(p.summary)}</strong></p>
    <span class="from">${esc(describeOps(p))}${p.source ? ` · from ${esc(p.source.title)}` : ""}</span>
    <div class="row-actions">
      <button class="btn primary" onclick="proposalAction(${p.id}, 'accept')">Yes, add it</button>
      <button class="btn" onclick="editProposal(${p.id})">Change something</button>
      <button class="btn quiet" onclick="hiddenOffers.add(${p.id}); render()">Not now</button>
      ${ready.length > 1 ? `<a class="btn quiet" href="#inbox">See all ${ready.length}</a>` : ""}
    </div></section>`;
}

const views = {};

views.today = async () => {
  const [h, t, n, sources] = await Promise.all([api("/api/health"), api("/api/today"), api("/api/note"), api("/api/sources"), loadLookups()]);
  const reading = sources.filter(s => s.status === "processing");
  todayIso = t.date;
  const soonEnd = iso(addDays(asDate(t.date), 14));
  const [cal, ask] = await Promise.all([api(`/api/calendar?start=${iso(addDays(asDate(t.date), 1))}&end=${soonEnd}`), offer()]);
  const week = termWeek(t.date);
  const comingUp = [...cal.deadlines.map(d => ({ ...d, kind: "deadlines", at: d.due })),
                    ...cal.unscheduled.map(x => ({ ...x, kind: "tasks", at: x.due }))].sort((a, b) => a.at.localeCompare(b.at)).slice(0, 6);
  const soon = d => (asDate(d) - asDate(t.date)) / 864e5 <= 4;
  const todays = [...t.overdue, ...t.tasks, ...t.done];
  const notify = !["localhost", "127.0.0.1"].includes(location.hostname) && !pushOn() && "Notification" in window && Notification.permission === "default";
  if (n.written_by === "plain") setTimeout(() => location.hash.startsWith("#today") || !location.hash ? refreshNote() : 0, 15000);
  return `<div class="page">
    <header class="head">
      <div class="dateline">${esc(fmtLong(t.date))}${week ? ` · ${week}` : ""}</div>
      <h1 id="note-h">${esc(n.headline)}</h1>
      <p class="voice" id="note-b">${esc(n.body)}</p>
    </header>
    ${h.ai.ready ? "" : `<div class="notice">I can't think right now: ${esc(h.ai.message)} Your plan still works.</div>`}
    ${reading.length ? `<p class="notice reading"><span class="spin"></span> Reading ${reading.map(s => esc(s.title)).join(", ")}. It takes a few minutes; what I find will show up here and in <a href="#inbox">Suggestions</a>.</p>` : ""}
    ${ask}
    <section aria-labelledby="h-today">
      <h2 id="h-today">Today${todays.length ? ` <span class="meta">${t.done.length} of ${todays.length} done</span>` : ""}</h2>
      ${t.overdue.length ? `<div class="meta">Still open from earlier</div>${t.overdue.map(taskItem).join("")}<div class="meta" style="margin-top:8px">Planned for today</div>` : ""}
      ${[...t.tasks, ...t.done].map(taskItem).join("") || `<p class="empty">Nothing planned for today.</p>`}
      ${t.deadlines.map(d => `<div class="item"><span class="when-row" style="padding:0"><span class="when due" style="width:auto">Due today</span></span>
        <a class="title" onclick='edit("deadlines", ${d.id})'>${esc(d.title)}</a>${courseTag(d.course_id)}</div>`).join("")}
      <button class="add-row" onclick='openEditor("tasks", null, {do_date: ${js(t.date)}})'>${ICON.plus}Add something for today</button>
    </section>
    ${t.events.length ? `<section aria-labelledby="h-sched"><h2 id="h-sched">Schedule</h2>
      ${t.events.map(e => `<div class="slot">
        <div class="time">${e.start.length > 10 ? `${esc(fmtTime(e.start))}${e.end ? `<br>${esc(fmtTime(e.end))}` : ""}` : "All day"}</div>
        <div class="body"><a class="title" style="color:inherit;text-decoration:none;font-weight:500;cursor:pointer" onclick='edit("events", ${e.id})'>${esc(e.title)}</a>
          <span class="meta">${[courseName(e.course_id), e.location].filter(Boolean).map(esc).join(" · ")}${e.provisional ? ` <span class="tag-prov">provisional</span>` : ""}</span></div>
      </div>`).join("")}</section>` : ""}
    <section aria-labelledby="h-next"><h2 id="h-next">Coming up</h2>
      ${comingUp.map(x => `<div class="when-row"><span class="when ${soon(x.at) ? "due" : ""}">${esc(fmtDay(x.at))}</span>
        <a class="what" onclick='edit("${x.kind}", ${x.id})'>${esc(x.title)}</a><span class="meta">${esc(courseName(x.course_id))}</span></div>`).join("")
        || `<p class="empty">Nothing due in the next two weeks that I know of.</p>`}
    </section>
    ${notify ? `<p class="meta"><a href="#settings">Turn on notifications</a> on this device for the morning note and check-ins.</p>` : ""}
  </div>
  ${composer("Reply, or tell me what's new…", "sayFromToday(event)")}`;
};

async function refreshNote() {
  try {
    const n = await api("/api/note");
    if (n.written_by === "assistant" && $("#note-h")) { $("#note-h").textContent = n.headline; $("#note-b").textContent = n.body; }
  } catch { }
}

// ---- Chat --------------------------------------------------------------------

// Just enough markdown for replies: **bold**, *italic*, `code`, "- " lists, paragraphs.
const md = s => esc(s).split(/\n{2,}/).map(par => {
  const lines = par.split("\n");
  if (lines.every(l => /^[-•] /.test(l))) return `<ul>${lines.map(l => `<li>${l.slice(2)}</li>`).join("")}</ul>`;
  return `<p>${lines.join("<br>")}</p>`;
}).join("").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>").replace(/`([^`]+)`/g, "<code>$1</code>");

const chatFocus = () => { try { return JSON.parse(sessionStorage.getItem("chatFocus")); } catch { return null; } };
function unfocus() { try { sessionStorage.removeItem("chatFocus"); } catch { } render(); }
const hhmm = s => fmtTime(s).replace(" ", " ");

function suggestionCard(m) {
  const pending = m.proposals.filter(p => p.status === "pending");
  const rows = m.proposals.map(p => `<label class="item">
    ${p.status === "pending" ? `<input type="checkbox" ${p.optional ? "" : "checked"} data-p="${p.id}">` : ""}
    <span class="title">${esc(p.summary)}</span>
    <span class="meta">${p.status === "pending" ? esc(describeOps(p)) : p.status === "accepted" ? "added" : "skipped"}</span></label>`).join("");
  return `<div class="sugg">${rows}
    ${pending.length ? `<div class="foot">
      <button class="btn primary small" onclick="acceptChecked(this)">${pending.length > 1 ? "Add these" : "Add it"}</button>
      <button class="btn small" onclick="editProposal(${pending[0].id})">Change something</button></div>` : ""}</div>`;
}

async function acceptChecked(button) {
  const ids = $$("input[data-p]:checked", button.closest(".sugg")).map(i => Number(i.dataset.p));
  button.disabled = true;
  for (const id of ids) { try { await api(`/api/proposals/${id}/accept`, { method: "POST" }); } catch (e) { toast(esc(detail(e))); } }
  render();
}

views.chat = async () => {
  const [c] = await Promise.all([api("/api/chat"), loadLookups()]);
  const focus = chatFocus();
  let lastDay = "";
  const turns = c.messages.map(m => {
    const day = m.created_at.slice(0, 10);
    const sep = day !== lastDay ? `<div class="day-sep">${esc(fmtLong(day))}</div>` : "";
    lastDay = day;
    if (m.role === "user") return `${sep}<div class="mine-wrap"><div class="mine">${esc(m.text)}</div>
      <button class="rewind" onclick="rewindTo(${m.id})" title="Undo this message and everything after it">${ICON.undo} Rewind</button></div>`;
    const isCurrent = c.current?.id === m.id;
    const body = isCurrent
      ? `<div class="ask-card"><p class="q">${esc(m.text)}</p>
          ${m.quote ? `<div class="from">From the source: “${esc(m.quote)}”</div>` : ""}
          ${c.current.options?.length ? `<div class="row-actions">${c.current.options.map(o => `<button class="btn" onclick="answerQuestion(${js(o)})">${esc(o)}</button>`).join("")}</div>` : ""}
          <div class="row-actions"><button class="btn quiet small" onclick="chatAction('skip')">Ask again later</button>
            <button class="btn quiet small" onclick="chatAction('dismiss')">Not relevant to me</button>
            ${c.waiting ? `<span class="meta">${c.waiting} more after this</span>` : ""}</div></div>`
      : `<div class="say">${md(m.text)}</div>`;
    return `${sep}<article class="turn"><div class="who"><b>Almanac</b> · ${esc(hhmm(m.created_at))}</div>${body}
      ${m.proposals?.length ? suggestionCard(m) : ""}</article>`;
  }).join("");
  setTimeout(() => {
    scrollTo(0, document.body.scrollHeight);
    if (pendingChat) { const t = pendingChat; pendingChat = null; sendChat(t); } else $("#say")?.focus();
  });
  return `<div class="page">
    ${c.messages.length ? `<div class="chat-tools"><button class="btn quiet small" onclick="clearChat()">Clear chat</button></div>` : ""}
    ${focus ? `<span class="focus-chip">About ${esc(focus.title)} <button class="icon-btn" style="width:26px;height:26px" onclick="unfocus()" aria-label="Stop focusing">${ICON.x}</button></span>` : ""}
    <div class="thread" id="thread">${turns || `<article class="turn"><div class="say">Tell me what's going on: classes, plans, things you keep meaning to do. I'll keep track and check in.</div></article>`}</div>
  </div>
  ${composer(c.current ? "Your answer…" : "Message Almanac…", "chatSend(event)")}`;
};

async function chatAction(action) { await api(`/api/chat/${action}`, { method: "POST" }); render(); }

function chatSend(e) {
  e.preventDefault();
  const box = e.target.elements.text, text = box.value.trim();
  if (!text) return;
  box.value = "";
  sendChat(text);
}

async function rewindTo(id) {
  if (!confirm("Rewind to this message? It and everything after it are removed, with what they changed in your plan "
               + "(suggestions, items added from them, answers and dates). Your message goes back in the reply box to edit.")) return;
  try {
    const r = await api(`/api/chat/rewind/${id}`, { method: "POST" });
    await render();
    const say = $("#say");
    if (say) { say.value = r.text; say.focus(); say.dispatchEvent(new Event("input")); }
  } catch (e) { toast(esc(detail(e))); }
}

async function clearChat() {
  if (!confirm("Clear the whole conversation? Your plan, suggestions and open questions stay as they are.")) return;
  await api("/api/chat/clear", { method: "POST" });
  render();
}

async function sendChat(text) {
  $("#thread").insertAdjacentHTML("beforeend", `<div class="mine">${esc(text)}</div>`);
  // the reply being written; after a message is saved, a line saying what's still going on
  const live = (html = `<span class="typing"><i></i><i></i><i></i></span>`) => {
    $("#live")?.remove();
    $("#thread")?.insertAdjacentHTML("beforeend", `<article class="turn" id="live"><div class="who"><b>Almanac</b></div><div class="say">${html}</div></article>`);
    scrollTo(0, document.body.scrollHeight);
    return $("#live .say");
  };
  let say = live(), reply = "", proposed = 0, replied = false;
  sending = true;
  // show what's been saved now, keeping a draft in the reply box
  const showSaved = async () => {
    if (!location.hash.startsWith("#chat")) return;
    const draft = $("#say")?.value;
    await render();
    if (draft && $("#say")) { $("#say").value = draft; $("#say").dispatchEvent(new Event("input")); }
    say = live(replied ? `<span class="waiting-line">Checking whether there's anything to add to your plan…</span>` : undefined);
  };
  try {
    const r = await fetch("/api/chat/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, focus: chatFocus() }) });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const events = buf.split("\n\n");
      buf = events.pop();
      for (const ev of events) {
        const e = JSON.parse(ev.replace(/^data: /, ""));
        if (e.type === "token") { reply += e.text; say.innerHTML = md(reply); scrollTo(0, document.body.scrollHeight); }
        else if (e.type === "said") { if (e.text === "assistant") replied = true; await showSaved(); }
        else if (e.type === "done") proposed = e.proposed;
        else if (e.type === "error") toast(`I couldn't reply: ${esc(e.text)}`);
      }
    }
  } catch (err) { toast(esc(detail(err))); }
  if (reply && !location.hash.startsWith("#chat"))  // you moved on while it was replying
    toast(`<b>Almanac replied</b><br>${esc(reply.length > 140 ? reply.slice(0, 140) + "…" : reply)} <a href="#chat">Open Chat</a>`);
  else if (proposed === null) toast("I couldn't pick out what to add from that: the model didn't answer in time (another app may be using it). Try again in a bit.");
  sending = false;
  await render();
}

// ---- Suggestions ---------------------------------------------------------------

const isRef = v => typeof v === "string" && /^\$(p\d+\.)?\d+$/.test(v);
let inboxCache = [];

function describeOps(p) {
  const kinds = new Set(p.ops.map(o => o.op + o.kind));
  if (p.ops.length > 2 && kinds.size === 1 && p.ops[0].op === "create") {
    // e.g. a task after each class: "17 tasks, due Mon, Oct 5 – Wed, Dec 2"
    const one = (KINDS[p.ops[0].kind]?.one || p.ops[0].kind).toLowerCase();
    const dates = p.ops.map(o => o.data?.due || o.data?.start || o.data?.deadline || o.data?.do_date).filter(Boolean).sort();
    return `${p.ops.length} ${one}s` + (dates.length ? `, ${p.ops[0].kind === "events" ? "" : "due "}${fmtDay(dates[0])} – ${fmtDay(dates[dates.length - 1])}` : "");
  }
  return p.ops.map(o => {
    const d = o.data || {}, one = KINDS[o.kind]?.one.toLowerCase() || o.kind;
    if (o.op === "delete") return `remove this ${one}`;
    if (o.op === "update") return Object.entries(d).map(([k, v]) =>
      k === "course_id" ? `course: ${isRef(v) ? "the new course" : courseName(v)}` : k === "project_id" ? "link it to its project"
        : k === "do_date" ? `move to ${fmtDay(v)}` : k === "status" ? (v === "done" ? "mark it done" : "reopen it")
        : ["due", "start", "deadline"].includes(k) ? `${fmtWhen(v)}` : k).join(", ");
    const when = d.do_date ? `on ${fmtDay(d.do_date)}` : d.due ? `due ${fmtWhen(d.due, d.window)}` : d.start
      ? (d.repeat ? `${d.repeat.split(",").map(x => x[0] + x[1].toLowerCase()).join("/")} ${fmtTime(d.start)}${d.end ? `–${fmtTime(d.end)}` : ""}` : fmtWhen(d.start, d.window))
      : d.deadline ? `by ${fmtWhen(d.deadline)}` : "no date yet";
    return o.kind === "courses" ? `new course${d.title ? `: ${d.title}` : ""}` : o.kind === "memories" ? "to remember" : `${one}, ${when}`;
  }).join("; ");
}

async function proposalAction(id, action) {
  try { await api(`/api/proposals/${id}/${action}`, { method: "POST" }); } catch (e) { toast(esc(detail(e))); }
  render();
}

async function acceptAll(sourceId) {
  const r = await api(`/api/sources/${sourceId}/accept-all`, { method: "POST" });
  if (r.skipped.length) toast(`Added ${r.accepted}. Not yet:<br>` + r.skipped.map(s => `• ${esc(s.summary)}: ${esc(s.reason)}`).join("<br>"));
  render();
}

async function editProposal(id) {
  await loadLookups();
  const p = inboxCache.find(p => p.id === id) || (await api("/api/inbox")).proposals.find(p => p.id === id);
  if (!p) return;
  const dlg = $("#editor");
  dlg.innerHTML = `<form method="dialog"><h2>Before I add it</h2>
    ${p.quote ? `<p class="why">“${esc(p.quote)}”</p>` : ""}
    ${p.ops.map((o, i) => o.op === "delete" ? `<p>Remove “${esc(o.id)}”</p>` : `<fieldset data-i="${i}"><legend>${esc(KINDS[o.kind].one)}</legend>
      ${KINDS[o.kind].fields.filter(f => !isRef(o.data?.[f[0]]) && (o.op === "create" || f[0] in o.data)).map(f => input(f, o.data?.[f[0]])).join("")}</fieldset>`).join("")}
    <p class="error" hidden></p>
    <div class="actions"><button type="button" class="btn quiet" data-act="reject">Don't add</button><span class="grow"></span>
      <button type="button" class="btn" data-act="cancel">Cancel</button><button class="btn primary">Add it</button></div></form>`;
  const form = $("form", dlg);
  $("[data-act=cancel]", form).onclick = () => dlg.close();
  $("[data-act=reject]", form).onclick = async () => { await proposalAction(id, "reject"); dlg.close(); };
  form.onsubmit = async e => {
    e.preventDefault();
    const ops = p.ops.map((o, i) => {
      const fs = form.querySelector(`fieldset[data-i="${i}"]`);
      if (!fs) return o;
      const data = { ...o.data, ...readForm(fs, o.kind) };
      for (const k of Object.keys(data)) if (data[k] === null && o.op === "create") delete data[k];
      return { ...o, data };
    });
    try { await send("POST", `/api/proposals/${id}/accept`, { ops }); dlg.close(); render(); }
    catch (err) { const el = $(".error", form); el.hidden = false; el.textContent = detail(err); }
  };
  dlg.showModal();
}

async function uploadFiles(files, replaces = null) {
  for (const f of files) {
    const body = new FormData();
    body.append("file", f);
    const r = await fetch(`/api/uploads${replaces ? `?replaces=${replaces}` : ""}`, { method: "POST", body });
    toast(r.ok ? `Reading ${esc(f.name)}. What I find will show up in <a href="#inbox">Suggestions</a>.` : esc(`${f.name}: ${await r.text()}`));
  }
  if (location.hash.startsWith("#inbox")) render();
  watchReading();
}

// A course website: the page and the sections it links to (schedule, syllabus…).
async function readSite(url, replaces = null) {
  url = (url || "").trim();
  if (!url) return;
  if (!/^https?:\/\//i.test(url)) url = "https://" + url;
  try {
    await api(`/api/uploads/url${replaces ? `?replaces=${replaces}` : ""}`, { method: "POST", body: JSON.stringify({ url }) });
    toast(`Reading ${esc(url)} and the pages it links to. What I find will show up in <a href="#inbox">Suggestions</a>.`);
  } catch (e) { toast(esc(detail(e))); }
  if (location.hash.startsWith("#inbox")) render();
  watchReading();
}

// While documents are being read, check every few seconds on any page; when
// one is done, show its notification ("Suggestions ready…") right away.
let readingIds = null, readingTimer;
async function watchReading() {
  clearTimeout(readingTimer);
  let sources;
  try { sources = await api("/api/sources"); } catch { readingTimer = setTimeout(watchReading, 10000); return; }
  const now = new Set(sources.filter(s => s.status === "processing").map(s => s.id));
  const finished = readingIds && [...readingIds].some(id => !now.has(id));
  const started = readingIds && [...now].some(id => !readingIds.has(id));
  readingIds = now;
  if (finished) await pollNotifications();
  if ((finished || started) && !sending && !$("#say")?.value && /^(#today|#inbox|)$/.test(location.hash)) render();
  else if (finished) refreshBadges();
  if (now.size) readingTimer = setTimeout(watchReading, 4000);
}
watchReading();

async function retryUpload(id, button) {
  button.disabled = true;
  try { await api(`/api/sources/${id}/retry`, { method: "POST" }); } catch (e) { toast(esc(detail(e))); }
  render(); watchReading();
}

const uploadRow = s => {
  const status = s.status === "processing" ? `<span class="spin"></span> reading…` : s.status === "failed" ? `<span class="bad">couldn't read it</span>` : "read";
  // what's still left out after a second look, each with why
  const why = { "quote not found in the document": "I couldn't find it in the document", "no date or lecture stated": "the document doesn't say when" };
  const dropped = s.dropped.length ? `<details class="upload-note"><summary>${s.dropped.length} thing${s.dropped.length > 1 ? "s" : ""} I couldn't place, even on a second look. I've asked you in <a href="#chat">Chat</a></summary>
    <ul>${s.dropped.map(d => `<li>${esc(d.title)}: ${esc(why[d.reason] || d.reason || "")}${d.quote ? ` (“${esc(d.quote)}”)` : ""}</li>`).join("")}</ul></details>` : "";
  const name = s.url ? `<a class="name" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.url)}">${esc(s.title)}</a>`
    : `<span class="name">${esc(s.title)}</span>`;
  return `<div class="upload">${ICON.doc}${name}<span class="meta">${status}</span>
    ${s.status === "failed" ? `<button class="btn small" onclick="retryUpload(${s.id}, this)">Try again</button>` : ""}
    ${s.status !== "processing" && s.url ? `<button class="btn small quiet" title="Read the site again: only changes will be suggested"
      onclick="readSite(${js(s.url)}, ${s.id})">Read again</button>` : ""}
    ${s.status !== "processing" && !s.url ? `<label class="btn small quiet" title="Upload an updated copy: only changes will be suggested">New version
      <input type="file" accept=".pdf,.docx,.txt,.md" hidden onchange="uploadFiles(this.files, ${s.id})"></label>` : ""}</div>
    ${s.error ? `<div class="upload-note">${esc(s.error)}</div>` : ""}${dropped}`;
};

let pollTimer;
views.inbox = async () => {
  const [box, sources] = await Promise.all([api("/api/inbox"), api("/api/sources"), loadLookups()]);
  clearTimeout(pollTimer);
  if (sources.some(s => s.status === "processing")) pollTimer = setTimeout(() => location.hash.startsWith("#inbox") && render(), 3000);
  inboxCache = box.proposals;
  const ready = box.proposals.filter(p => !p.blocked_by), waiting = box.proposals.filter(p => p.blocked_by);
  const groups = {};
  for (const p of ready) (groups[p.source?.id ?? 0] ??= { source: p.source, items: [] }).items.push(p);
  const card = p => `<div class="card ${p.blocked_by ? "waiting" : ""}">
    <p class="summary">${esc(p.summary)}${p.optional ? ` <span class="tag">optional</span>` : ""}</p>
    <p class="detail">${esc(describeOps(p))}</p>
    ${p.quote ? `<p class="why">“${esc(p.quote)}”</p>` : ""}
    ${p.blocked_by ? `<p class="detail">Waiting on your answer in <a href="#chat">Chat</a>: ${esc(p.blocked_by)}</p>` : `<div class="row-actions">
      <button class="btn primary small" onclick="proposalAction(${p.id}, 'accept')">Add it</button>
      <button class="btn small" onclick="editProposal(${p.id})">Change something</button>
      <button class="btn quiet small" onclick="proposalAction(${p.id}, 'reject')">Don't add</button></div>`}
  </div>`;
  const listed = Object.values(groups).map(g => `<section>
    <div class="group-head"><h2>${esc(g.source?.title || "From planning")}</h2>
      ${g.source && g.items.length > 1 ? `<button class="btn small" onclick="acceptAll(${g.source.id})">Add all ${g.items.length}</button>` : ""}</div>
    ${g.items.map(card).join("")}</section>`).join("");
  return `<div class="page">
    <header class="head"><h1>Suggestions</h1>
      <p class="voice small">${ready.length ? `${ready.length} thing${ready.length > 1 ? "s" : ""} I'd like to add. Nothing changes until you say yes.` : "Nothing waiting. Send me a syllabus or tell me in Chat, and I'll suggest what to add."}</p></header>
    <section>
      <label class="drop" ondragover="event.preventDefault(); this.classList.add('over')" ondragleave="this.classList.remove('over')"
        ondrop="event.preventDefault(); this.classList.remove('over'); uploadFiles(event.dataTransfer.files)">
        ${ICON.doc}<span><b>Add a syllabus or document</b><br>PDF, DOCX or text. Drop it here or click.</span>
        <input type="file" multiple accept=".pdf,.docx,.txt,.md" hidden onchange="uploadFiles(this.files)"></label>
      <form class="site-form" onsubmit="event.preventDefault(); readSite(this.url.value); this.reset()">
        <input name="url" type="text" inputmode="url" placeholder="Or paste a course website address" aria-label="Course website address" required>
        <button class="btn small">Read it</button></form>
      ${sources.slice(0, 6).map(uploadRow).join("")}
    </section>
    ${listed}
    ${waiting.length ? `<details class="later"><summary>${waiting.length} more waiting on your answers</summary>${waiting.map(card).join("")}</details>` : ""}
  </div>`;
};

// ---- Calendar ------------------------------------------------------------------

const cal = { mode: sessionStorage.getItem("calMode") || "week", anchor: null, day: null };
const narrow = () => matchMedia("(max-width: 760px)").matches;
const HOUR = 56;

function calNav(step) {
  const a = cal.anchor;
  cal.anchor = step === 0 ? null : cal.mode === "month" && !narrow() ? new Date(a.getFullYear(), a.getMonth() + step, 1) : addDays(a, 7 * step);
  cal.day = step === 0 ? null : cal.day && iso(addDays(asDate(cal.day), 7 * step));
  render();
}

async function dropTask(e, day) {
  e.preventDefault();
  e.currentTarget.classList.remove("over");
  await send("PATCH", `/api/tasks/${e.dataTransfer.getData("text/plain")}`, { do_date: day });
  render();
}

function weekLine(data, first) {
  // what a person would say about the week, from the numbers
  const name = i => addDays(first, i).toLocaleDateString("en-US", { weekday: "long" });
  const load = Array(7).fill(0);
  for (const e of data.events) if (e.end && e.start.length > 10) load[Math.round((asDate(e.start.slice(0, 10)) - first) / 864e5)] += hours(e.end) - hours(e.start);
  const long = load.map((h, i) => [h, i]).filter(([h]) => h >= 3);
  const due = data.deadlines.filter(d => d.due.slice(0, 10) >= todayIso);
  const parts = [];
  if (long.length) {
    const names = long.map(([, i]) => name(i));
    const avg = Math.round(long.reduce((s, [h]) => s + h, 0) / long.length * 2) / 2;
    parts.push(`${names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names.at(-1) + " are your long days" : names[0] + " is your long day"}: about ${avg} hours of class${names.length > 1 ? " each" : ""}.`);
  }
  if (due.length) parts.push(`${due.length === 1 ? `One thing is due: ${due[0].title}, ${fmtDay(due[0].due)}` : `${due.length} things are due, the first ${due[0].title} on ${fmtDay(due[0].due)}`}.`);
  return parts.join(" ") || "A quiet week on the calendar so far.";
}

function chipFor(kind, x) {
  const label = kind === "deadlines" ? `Due: ${x.title}` : kind === "events" ? `${x.start.length > 10 ? fmtTime(x.start) + " " : ""}${x.title}` : `○ ${x.title}`;
  const cls = ["chip", kind === "tasks" ? "task" : kind === "deadlines" ? "dl" : "ev2", x.status === "done" ? "done" : "", x.provisional || x.window ? "prov" : "", x.unscheduled ? "faint" : ""].join(" ");
  const drag = kind === "tasks" ? `draggable="true" ondragstart="event.dataTransfer.setData('text/plain', ${x.id})"` : "";
  const tip = [x.title, courseName(x.course_id), x.window ? "sometime that week (the day isn't stated)" : "", x.provisional ? "provisional" : "", x.unscheduled ? "no day to do it yet" : ""].filter(Boolean).join(" · ");
  return `<div class="${cls}" ${drag} title="${esc(tip)}" onclick='edit("${kind}", ${x.id})'>${esc(label)}</div>`;
}

views.calendar = async () => {
  const t = await api("/api/today");
  todayIso = t.date;
  const today = asDate(t.date);
  cal.anchor ??= today;
  return narrow() ? agenda(today) : cal.mode === "month" ? month(today) : weekGrid(today);
};

function calHeader(title, line) {
  return `<header class="head">
    <div class="cal-bar"><h1>${esc(title)}</h1>
      <button class="icon-btn" onclick="calNav(-1)" aria-label="Previous">${ICON.left}</button>
      <button class="btn small" onclick="calNav(0)">Today</button>
      <button class="icon-btn" onclick="calNav(1)" aria-label="Next">${ICON.right}</button>
      ${narrow() ? "" : `<div class="seg" role="group" aria-label="View">${["week", "month"].map(m => `<button class="${m === cal.mode ? "on" : ""}" onclick='cal.mode="${m}"; sessionStorage.setItem("calMode", "${m}"); render()'>${m[0].toUpperCase() + m.slice(1)}</button>`).join("")}</div>`}
    </div>
    ${line ? `<p class="voice small">${esc(line)}</p>` : ""}</header>`;
}

function layoutLanes(events) {
  // events that overlap share the column side by side: event → [lane, lanes in its group]
  const out = new Map();
  const byDay = {};
  for (const e of events) (byDay[e.start.slice(0, 10)] ??= []).push(e);
  for (const list of Object.values(byDay)) {
    list.sort((a, b) => a.start.localeCompare(b.start));
    let group = [], ends = [], groupEnd = -1;
    const close = () => group.forEach(([e, l]) => out.set(e, [l, ends.length]));
    for (const e of list) {
      const s = hours(e.start), f = e.end ? hours(e.end) : s + 1;
      if (s >= groupEnd) { close(); group = []; ends = []; }
      let lane = ends.findIndex(x => x <= s);
      if (lane < 0) { lane = ends.length; ends.push(f); } else ends[lane] = f;
      group.push([e, lane]);
      groupEnd = Math.max(groupEnd, f);
    }
    close();
  }
  return out;
}

async function weekGrid(today) {
  const first = monday(cal.anchor);
  const [data] = await Promise.all([api(`/api/calendar?start=${iso(first)}&end=${iso(addDays(first, 6))}`), loadLookups()]);
  const timed = data.events.filter(e => e.start.length > 10);
  // the hours that matter this week: an hour either side of its classes and events
  const lo = timed.length ? Math.max(6, Math.min(...timed.map(e => Math.floor(hours(e.start)))) - 1) : 8;
  const hi = timed.length ? Math.min(24, Math.max(...timed.map(e => Math.ceil(e.end ? hours(e.end) : hours(e.start) + 1))) + 1) : 18;
  const lanes = layoutLanes(timed);
  const days = [...Array(7)].map((_, i) => iso(addDays(first, i)));
  const allday = Object.fromEntries(days.map(d => [d, []]));
  data.events.filter(e => e.start.length === 10).forEach(e => allday[e.start]?.push(chipFor("events", e)));
  data.deadlines.forEach(d => allday[d.due.slice(0, 10)]?.push(chipFor("deadlines", d)));
  data.tasks.forEach(x => allday[x.do_date]?.push(chipFor("tasks", x)));
  data.unscheduled.forEach(x => allday[x.due.slice(0, 10)]?.push(chipFor("tasks", { ...x, unscheduled: true })));
  const now = new Date(), nowH = now.getHours() + now.getMinutes() / 60;
  const head = days.map(d => `<div class="dh ${d === todayIso ? "today" : ""}">${asDate(d).toLocaleDateString("en-US", { weekday: "short" })}<b>${asDate(d).getDate()}</b></div>`).join("");
  const top = days.map(d => `<div class="allday ${d === todayIso ? "today" : ""}" ondragover="event.preventDefault(); this.classList.add('over')"
      ondragleave="this.classList.remove('over')" ondrop="dropTask(event, '${d}')">${allday[d].join("")}</div>`).join("");
  const cols = days.map(d => `<div class="col ${d === todayIso ? "today" : ""}" style="height:${(hi - lo) * HOUR}px">
      ${[...Array(hi - lo)].map((_, i) => `<div class="hl" style="top:${i * HOUR}px"></div>`).join("")}
      ${timed.filter(e => e.start.slice(0, 10) === d).map(e => {
        const s = hours(e.start), f = e.end ? hours(e.end) : s + 1, [lane, of] = lanes.get(e);
        const place = of > 1 ? `left:calc(${(100 / of) * lane}% + 3px);right:calc(${100 - (100 / of) * (lane + 1)}% + 3px);` : "";
        return `<div class="ev ${e.provisional ? "prov" : ""}" style="${place}top:${(s - lo) * HOUR + 1}px;height:${Math.max(22, (f - s) * HOUR - 3)}px;--c:${courseTint(e.course_id)}"
          onclick='edit("events", ${e.id})' title="${esc(e.title)}"><b>${esc(e.title)}</b>${esc(fmtTime(e.start))}${e.end ? `–${esc(fmtTime(e.end))}` : ""}${e.location ? ` · ${esc(e.location)}` : ""}</div>`;
      }).join("")}
      ${d === todayIso && nowH >= lo && nowH <= hi ? `<div class="now" style="top:${(nowH - lo) * HOUR}px"></div>` : ""}</div>`).join("");
  const legend = lookups.courses.map(c => `<span><i class="swatch" style="background:${courseColor(c.id)}"></i>${esc(courseName(c.id))}</span>`).join("");
  return `<div class="page cal">
    ${calHeader(`${fmtDay(days[0]).replace(/^\w+, /, "")} – ${fmtDay(days[6]).replace(/^\w+, /, "")}`, weekLine(data, first))}
    ${legend ? `<div class="legend">${legend}</div>` : ""}
    <div class="week"><div></div>${head}<div class="gutter" style="padding-top:8px">all day</div>${top}
      <div class="hours">${[...Array(hi - lo)].map((_, i) => `<div>${((lo + i) % 12) || 12} ${lo + i < 12 ? "AM" : "PM"}</div>`).join("")}</div>${cols}</div>
    <p class="meta">Drag a task to another day to move it. Dashed: the source didn't fix the day or time.</p>
  </div>`;
}

async function month(today) {
  const a = cal.anchor, first = monday(new Date(a.getFullYear(), a.getMonth(), 1));
  const n = Math.ceil(((new Date(a.getFullYear(), a.getMonth() + 1, 0) - first) / 864e5 + 1) / 7) * 7;
  const [data] = await Promise.all([api(`/api/calendar?start=${iso(first)}&end=${iso(addDays(first, n - 1))}`), loadLookups()]);
  const by = {};
  const put = (d, html) => (by[d] ??= []).push(html);
  data.events.forEach(e => put(e.start.slice(0, 10), chipFor("events", e)));
  data.deadlines.forEach(d => put(d.due.slice(0, 10), chipFor("deadlines", d)));
  data.tasks.forEach(x => put(x.do_date, chipFor("tasks", x)));
  data.unscheduled.forEach(x => put(x.due.slice(0, 10), chipFor("tasks", { ...x, unscheduled: true })));
  const cells = [...Array(n)].map((_, i) => {
    const d = addDays(first, i), day = iso(d);
    return `<div class="cell ${d.getMonth() !== a.getMonth() ? "out" : ""} ${day === todayIso ? "today" : ""}" ondragover="event.preventDefault(); this.classList.add('over')"
      ondragleave="this.classList.remove('over')" ondrop="dropTask(event, '${day}')"><span class="n">${d.getDate()}</span>${(by[day] || []).join("")}</div>`;
  }).join("");
  return `<div class="page cal">
    ${calHeader(a.toLocaleDateString("en-US", { month: "long", year: "numeric" }), "")}
    <div class="month">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(d => `<div class="dow">${d}</div>`).join("")}${cells}</div></div>`;
}

async function agenda(today) {
  const first = monday(cal.anchor);
  const days = [...Array(7)].map((_, i) => iso(addDays(first, i)));
  cal.day = cal.day && days.includes(cal.day) ? cal.day : days.includes(todayIso) ? todayIso : days[0];
  const [data] = await Promise.all([api(`/api/calendar?start=${days[0]}&end=${days[6]}`), loadLookups()]);
  const on = d => [
    ...data.events.filter(e => e.start.slice(0, 10) === d).map(e => ({ t: e.start.length > 10 ? fmtTime(e.start) : "All day", sort: e.start, html:
      `<div class="box ev ${e.provisional ? "unset" : ""}" style="--c:${courseTint(e.course_id)}" onclick='edit("events", ${e.id})'><span>${esc(e.title)}</span>
       <span class="meta">${[e.end ? `until ${fmtTime(e.end)}` : "", courseName(e.course_id), e.location].filter(Boolean).map(esc).join(" · ")}</span></div>` })),
    ...data.deadlines.filter(x => x.due.slice(0, 10) === d).map(x => ({ t: "Due", due: true, sort: x.due, html:
      `<div class="box dl" onclick='edit("deadlines", ${x.id})'><span>${esc(x.title)}</span><span class="meta">${esc(courseName(x.course_id))}</span></div>` })),
    ...data.tasks.filter(x => x.do_date === d).map(x => ({ t: "Any time", sort: d, html:
      `<div class="box" onclick='edit("tasks", ${x.id})'><span style="${x.status === "done" ? "text-decoration:line-through;color:var(--faint)" : ""}">${esc(x.title)}</span>
       <span class="meta">${[courseName(x.course_id), est(x.estimate_min)].filter(Boolean).map(esc).join(" · ")}</span></div>` })),
  ].sort((a, b) => a.sort.localeCompare(b.sort));
  const strip = days.map(d => `<button class="${d === cal.day ? "on" : ""}" onclick="cal.day='${d}'; render()" aria-pressed="${d === cal.day}">
      ${asDate(d).toLocaleDateString("en-US", { weekday: "narrow" })}<b>${asDate(d).getDate()}</b>${on(d).length ? "<i></i>" : ""}</button>`).join("");
  const later = days.filter(d => d > cal.day && on(d).length);
  const dayBlock = d => `<div class="day">${d === cal.day ? "" : `<h2>${esc(fmtLong(d))}</h2>`}
    ${on(d).map(x => `<div class="ag"><div class="t ${x.due ? "due" : ""}">${esc(x.t)}</div>${x.html}</div>`).join("") || `<p class="empty">Nothing on this day.</p>`}</div>`;
  return `<div class="page cal">
    ${calHeader(asDate(cal.day).toLocaleDateString("en-US", { month: "long" }), "")}
    <div class="strip" role="group" aria-label="This week">${strip}</div>
    <div class="agenda">${dayBlock(cal.day)}${later.map(dayBlock).join("")}</div></div>`;
}

// ---- Goals -------------------------------------------------------------------

function discuss(kind, id, title) {
  try { sessionStorage.setItem("chatFocus", JSON.stringify({ kind, id, title })); } catch { }
  location.hash = "#chat";
}

async function suggestNextSteps(button) {
  button.disabled = true;
  button.textContent = "Thinking…";
  try {
    const r = await api("/api/goals/next-steps", { method: "POST" });
    toast(r.proposed ? `I suggested ${r.proposed} next step${r.proposed > 1 ? "s" : ""}. They're in <a href="#inbox">Suggestions</a>.`
                     : "Every goal already has something to do, or a suggestion waiting.");
  } catch (e) { toast(esc(detail(e))); }
  render();
}

async function planProject(id, button) {
  button.disabled = true;
  button.textContent = "Planning…";
  try {
    const r = await send("POST", `/api/projects/${id}/plan`, {});
    toast(`${esc(r.proposal.summary)}. It's in <a href="#inbox">Suggestions</a>.` + (r.warnings.length ? `<br>${r.warnings.map(esc).join("<br>")}` : ""));
  } catch (e) { toast(esc(detail(e))); }
  render();
}

const projectCard = p => {
  const total = p.open + p.done, pct = total ? Math.round(100 * p.done / total) : 0;
  return `<div class="card">
    <div class="group-head"><a class="summary" style="flex:1;color:inherit;text-decoration:none;cursor:pointer" onclick='edit("projects", ${p.id})'>${esc(p.title)}</a>
      ${courseTag(p.course_id)}<span class="meta">${p.deadline ? `by ${esc(fmtWhen(p.deadline))}` : ""}</span></div>
    <div class="bar"><span style="width:${pct}%"></span></div>
    <p class="detail">${total ? `${p.done} of ${total} done` : "No steps yet"}${p.next ? `. Next: <b style="font-weight:500">${esc(p.next.title)}</b>${p.next.do_date ? `, ${esc(fmtDay(p.next.do_date))}` : ""}` : ""}</p>
    <div class="row-actions">
      ${p.deadline ? `<button class="btn small" onclick="planProject(${p.id}, this)">${total ? "Replan it" : "Plan it with me"}</button>` : ""}
      <button class="btn small quiet" onclick="discuss('projects', ${p.id}, ${js(p.title)})">Talk it through</button>
    </div></div>`;
};

views.goals = async () => {
  const [b] = await Promise.all([api("/api/board"), loadLookups()]);
  const goals = b.goals.map(g => `<section class="goal">
    <div class="group-head"><h2>${esc(g.title)}</h2>
      <button class="btn small quiet" onclick="discuss('goals', ${g.id}, ${js(g.title)})">Talk it through</button>
      <button class="btn small" onclick='openEditor("projects", null, {goal_id: ${g.id}})'>Add a project</button></div>
    ${g.why || g.horizon ? `<p class="voice small" style="margin:0">${esc([g.why, g.horizon && `(${g.horizon})`].filter(Boolean).join(" "))}</p>` : ""}
    ${g.projects.map(projectCard).join("") || `<p class="empty">No projects yet. I can suggest a first step.</p>`}</section>`).join("");
  return `<div class="page">
    <header class="head"><h1>Goals</h1>
      <p class="voice small">What you're working toward. I'll make sure each one always has a next step.</p>
      <div class="row-actions"><button class="btn primary" onclick='openEditor("goals")'>Add a goal</button>
        <button class="btn" onclick="suggestNextSteps(this)">Suggest next steps</button></div></header>
    ${goals || `<p class="empty">No goals yet. Tell me in <a href="#chat">Chat</a> what you're working toward, or add one.</p>`}
    ${b.projects.length ? `<section><h2>Other projects</h2>${b.projects.map(projectCard).join("")}</section>` : ""}
  </div>`;
};

// ---- a course ----------------------------------------------------------------

views.course = async (id) => {
  id = Number(id);
  await loadLookups();
  const c = lookups.courses.find(c => c.id === id);
  if (!c) return `<div class="page"><p class="empty">That course isn't in your plan.</p></div>`;
  const [deadlines, tasks, events, projects, lectures] = await Promise.all(
    ["deadlines", "tasks", "events", "projects", "recordings"].map(k => api(`/api/${k}?course_id=${id}`)));
  const t = await api("/api/today");
  const upcoming = [...deadlines.filter(d => d.due && d.due.slice(0, 10) >= t.date).map(d => ({ ...d, kind: "deadlines", at: d.due })),
                    ...events.filter(e => !e.repeat && e.start.slice(0, 10) >= t.date).map(e => ({ ...e, kind: "events", at: e.start })),
                    ...tasks.filter(x => x.status === "open").map(x => ({ ...x, kind: "tasks", at: x.do_date || x.due || "9999" }))]
    .sort((a, b) => a.at.localeCompare(b.at));
  const meets = events.filter(e => e.repeat);
  return `<div class="page">
    <header class="head"><div class="dateline"><i class="swatch" style="background:${courseColor(id)}"></i> ${esc(c.number)}</div>
      <h1>${esc(c.title || courseName(id))}</h1>
      <p class="voice small">${esc(c.number)} with ${esc(c.instructor)}.</p>
      <div class="row-actions"><button class="btn small" onclick='edit("courses", ${id})'>Edit course</button></div></header>
    ${meets.length ? `<section><h2>Class</h2>${meets.map(e => `<div class="when-row"><span class="when">${esc(e.repeat.split(",").map(x => x[0] + x[1].toLowerCase()).join("/"))}</span>
      <a class="what" onclick='edit("events", ${e.id})'>${esc(fmtTime(e.start))}${e.end ? `–${esc(fmtTime(e.end))}` : ""}${e.location ? ` · ${esc(e.location)}` : ""}</a></div>`).join("")}</section>` : ""}
    <section><h2>Coming up</h2>
      ${upcoming.map(x => `<div class="when-row"><span class="when ${x.kind === "deadlines" ? "due" : ""}">${x.at === "9999" ? "No date" : esc(fmtDay(x.at))}</span>
        <a class="what" onclick='edit("${x.kind}", ${x.id})'>${x.kind === "deadlines" ? "Due: " : ""}${esc(x.title)}</a></div>`).join("") || `<p class="empty">Nothing coming up.</p>`}</section>
    ${projects.length ? `<section><h2>Projects</h2>${projects.map(p => `<div class="when-row"><span class="when">${p.deadline ? esc(fmtDay(p.deadline)) : ""}</span>
      <a class="what" onclick='edit("projects", ${p.id})'>${esc(p.title)}</a></div>`).join("")}</section>` : ""}
    <section><div class="group-head"><h2>Lectures</h2>
      <a class="btn small" href="#record/${id}">Record a lecture</a>
      <label class="btn small quiet" title="A recording made with the laptop's recorder, a phone voice memo or a Zoom download">Upload a recording
        <input type="file" accept="audio/*,video/*" hidden onchange="uploadRecording(${id}, this.files)"></label></div>
      ${lectures.map(lectureRow).join("") || `<p class="empty">No lectures yet. Upload a recording, and I'll write it up as a clean transcript.</p>`}</section>
  </div>`;
};

// ---- Lectures (Recordings) ----------------------------------------------------

const LECTURE_STATUS = { transcribing: "transcribing…", cleaning: "cleaning up the text…", failed: "couldn't transcribe" };
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const lectureRow = r => `<div class="when-row"><span class="when">${esc(fmtDay(r.date))}</span>
  <a class="what" href="#lecture/${r.id}">${r.kind_name ? `${esc(r.kind_name)} · ` : ""}${r.status === "done" ? (r.transcript ? `${Math.max(1, Math.round(r.seconds / 60))} min transcript` : "Transcript deleted")
    : `${r.status === "failed" ? "" : `<span class="spin"></span> `}${esc(LECTURE_STATUS[r.status] || r.status)}`}</a></div>`;

async function uploadRecording(courseId, files) {
  const f = files[0];
  if (!f) return;
  const body = new FormData();
  body.append("file", f);
  // the lecture's date: when the file was made (a recording uploaded later is still that day's lecture)
  const d = new Date(f.lastModified || Date.now()), day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const r = await fetch(`/api/recordings?course_id=${courseId}&date=${day}`, { method: "POST", body });
  toast(r.ok ? `Transcribing ${esc(f.name)}. I'll let you know when the transcript is ready; the audio is deleted once it is.` : esc(detail(new Error(`${r.status} ${await r.text()}`))));
  render();
}

// "[?]": a word the transcript isn't sure of, underlined rather than asked about
const unclear = t => esc(t).replace(/(\S+) \[\?\]/g, `<span class="unclear" title="Not sure this was heard right">$1</span>`);

// Lecture notes: "## " sections, "### " subsections, "- " points nested by two
// spaces, "✎ " the student's own lines, "Almanac: " the assistant's own links.
function notesMd(text) {
  const inline = t => unclear(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/`([^`]+)`/g, "<code>$1</code>").replace(/^Almanac:/, `<span class="almanac">Almanac:</span>`);
  let html = "", depth = 0;
  const close = to => { while (depth > to) { html += "</ul>"; depth--; } };
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) continue;
    const head = line.match(/^(#{1,3})\s+(.*)/);
    if (head) { close(0); html += head[1].length === 3 ? `<h4>${inline(head[2])}</h4>` : `<h3>${inline(head[2])}</h3>`; continue; }
    const point = line.match(/^(\s*)[-*]\s+(.*)/), jot = line.match(/^(\s*)✎\s*(.*)/);
    if (point || jot) {
      const level = Math.floor((point || jot)[1].length / 2) + 1;
      while (depth < level) { html += "<ul>"; depth++; }
      close(level);
      html += jot ? `<li class="jot"><span class="pen" title="You wrote this during the lecture">✎</span> ${/^\(marked\)$/.test(jot[2].trim()) ? "<i>marked</i>" : inline(jot[2])}</li>`
        : `<li${/^Almanac:/.test(point[2]) ? ' class="almanac-line"' : ""}>${inline(point[2])}</li>`;
      continue;
    }
    close(0);
    html += `<p>${inline(line.trim())}</p>`;
  }
  close(0);
  return html;
}

views.lecture = async (id) => {
  const r = await api(`/api/recordings/${id}`);
  await loadLookups();
  const course = lookups.courses.find(c => c.id === r.course_id);
  const transcript = r.transcript ? `<div class="transcript">${r.transcript.map(s => `<p><span class="ts">${mmss(s.start)}</span><span>${unclear(s.text)}</span></p>`).join("")}</div>`
    : `<p class="empty">You deleted this transcript.</p>`;
  const notes = r.notes ? `<section class="notes">${notesMd(r.notes)}</section>`
    : r.notes_status === "writing" ? `<p class="voice small"><span class="spin"></span> Writing your notes from the transcript${r.jottings.length ? " and your jottings" : ""}…</p>`
    : r.notes_status === "failed" ? `<div class="notice">I couldn't write the notes: ${esc(r.notes_error || "")}
        <div class="row-actions"><button class="btn small" onclick="retryNotes(${r.id})">Write again</button></div></div>` : "";
  const body = r.status === "done"
    ? `${notes}${r.notes ? `<details class="later"><summary>Transcript</summary>${transcript}</details>` : `<section>${transcript}</section>`}`
    : r.status === "failed" ? `<div class="notice">${esc(r.error || "Something went wrong.")}</div>
        ${r.retry ? `<button class="btn small" onclick="retryLecture(${r.id})">Clean up again</button>` : ""}`
    : `<p class="voice small"><span class="spin"></span> ${esc(LECTURE_STATUS[r.status])} This takes about a minute per 15 minutes of lecture.</p>`;
  return `<div class="page">
    <header class="head"><div class="dateline">${course ? `<a href="#course/${course.id}">${esc(course.number)} · ${esc(course.instructor)}</a>` : "Lecture"}</div>
      <h1>${esc(fmtLong(r.date))}</h1>
      ${r.kind_name ? `<p class="voice small">${esc(r.kind_name)}${r.papers.length ? `: ${r.papers.map(esc).join("; ")}` : ""}</p>` : ""}
      ${r.status === "done" && r.transcript ? `<p class="voice small">${Math.max(1, Math.round(r.seconds / 60))} minute${Math.round(r.seconds / 60) > 1 ? "s" : ""}.
        ${r.notes ? "Lines marked ✎ are yours. " : ""}Underlined words are ones I'm not sure were heard right.</p>
        <div class="row-actions"><button class="btn quiet small" onclick="deleteTranscript(${r.id})">Delete transcript</button></div>` : ""}</header>
    ${r.jottings.length && !r.notes ? `<section><h2>Your jottings</h2>${r.jottings.map(j => `<div class="jotting"><span class="ts">${mmss(j.at)}</span>
      <span class="what">${j.text ? esc(j.text) : `<i class="mark">Marked</i>`}</span></div>`).join("")}</section>` : ""}
    ${body}
  </div>`;
};

async function retryNotes(id) {
  try { await api(`/api/recordings/${id}/notes/retry`, { method: "POST" }); } catch (e) { toast(esc(detail(e))); }
  render();
}

async function deleteTranscript(id) {
  if (!confirm("Delete this transcript? The lecture stays in the list; the text can't be brought back (the audio is already gone).")) return;
  await api(`/api/recordings/${id}/transcript`, { method: "DELETE" });
  render();
}

async function retryLecture(id) {
  try { await api(`/api/recordings/${id}/retry`, { method: "POST" }); } catch (e) { toast(esc(detail(e))); }
  render();
}

// ---- Plan (everything, by kind) ------------------------------------------------

views.plan = async () => {
  const tab = sessionStorage.getItem("planTab") || "tasks";
  const [items] = await Promise.all([api(`/api/${tab}`), loadLookups()]);
  const row = {
    tasks: taskItem,
    events: e => `<div class="when-row"><span class="when">${e.repeat ? esc(e.repeat.split(",").map(x => x[0] + x[1].toLowerCase()).join("/")) : esc(fmtDay(e.start))}</span>
      <a class="what" onclick='edit("events", ${e.id})'>${esc(e.title)}</a><span class="meta">${esc(fmtTime(e.start))}</span></div>`,
    deadlines: d => `<div class="when-row"><span class="when due">${d.due ? esc(fmtDay(d.due)) : "No date"}</span>
      <a class="what" onclick='edit("deadlines", ${d.id})'>${esc(d.title)}</a><span class="meta">${esc(courseName(d.course_id))}</span></div>`,
    projects: p => `<div class="when-row"><span class="when">${p.deadline ? esc(fmtDay(p.deadline)) : ""}</span>
      <a class="what" onclick='edit("projects", ${p.id})'>${esc(p.title)}</a><span class="meta">${esc(courseName(p.course_id))}</span></div>`,
    goals: g => `<div class="when-row"><span class="when">${esc(g.horizon || "")}</span><a class="what" onclick='edit("goals", ${g.id})'>${esc(g.title)}</a></div>`,
    courses: c => `<div class="when-row"><span class="when"><i class="swatch" style="background:${courseColor(c.id)}"></i></span>
      <a class="what" onclick='edit("courses", ${c.id})'>${esc(c.number)} · ${esc(c.instructor)}</a><span class="meta">${esc(c.title || "")}</span></div>`,
    terms: t => `<div class="when-row"><span class="when">${esc(t.name)}</span><a class="what" onclick='edit("terms", ${t.id})'>Week 1 starts ${esc(fmtDay(t.week1))}; classes end ${esc(fmtDay(t.instruction_ends))}</a></div>`,
  }[tab];
  const tabs = ["tasks", "events", "deadlines", "projects", "goals", "courses", "terms"];
  return `<div class="page">
    <header class="head"><h1>Plan</h1><p class="voice small">Everything I'm keeping track of, by kind.</p>
      <div class="tabs">${tabs.map(k => `<button class="${k === tab ? "on" : ""}" onclick='sessionStorage.setItem("planTab", "${k}"); render()'>${KINDS[k].one}s</button>`).join("")}</div></header>
    <section>${items.map(row).join("") || `<p class="empty">No ${KINDS[tab].one.toLowerCase()}s yet.</p>`}
      <button class="add-row" onclick='openEditor("${tab}")'>${ICON.plus}Add a ${KINDS[tab].one.toLowerCase()}</button></section>
  </div>`;
};

// ---- What I remember ---------------------------------------------------------

async function saveCapacity(e) {
  e.preventDefault();
  const f = e.target.elements;
  try { await send("PUT", "/api/capacity", { weekday: Number(f.weekday.value), weekend: Number(f.weekend.value) }); toast("Saved."); }
  catch (err) { toast(esc(detail(err))); }
}

views.memory = async () => {
  const [mems, cap] = await Promise.all([api("/api/memories"), api("/api/capacity")]);
  const byTopic = {};
  for (const m of mems) (byTopic[m.topic || "Other things"] ??= []).push(m);
  return `<div class="page">
    <header class="head"><h1>What I remember</h1>
      <p class="voice small">Everything I know about you, and use when I plan. I only remember what you've said yes to.</p></header>
    <section><h2>How much you want to do in a day</h2>
      <form class="capacity" onsubmit="saveCapacity(event)">
        <label>Weekdays <input name="weekday" type="number" min="0" max="16" step="0.5" value="${cap.weekday}"> hours</label>
        <label>Weekends <input name="weekend" type="number" min="0" max="16" step="0.5" value="${cap.weekend}"> hours</label>
        <button class="btn small">Save</button></form>
      <p class="meta">A soft limit. I'll tell you when a day goes over; I won't stop you.</p></section>
    ${Object.entries(byTopic).map(([t, ms]) => `<section><h2>${esc(t[0].toUpperCase() + t.slice(1))}</h2>${ms.map(m =>
      `<div class="item"><a class="title" onclick='edit("memories", ${m.id})'>${esc(m.text)}</a></div>`).join("")}</section>`).join("")
      || `<p class="empty">Nothing yet. When you tell me things in Chat (how fast you read, when you work best), I'll ask before I remember them.</p>`}
    <button class="add-row" onclick='openEditor("memories")'>${ICON.plus}Tell me something to remember</button>
  </div>`;
};

// ---- Reviews -----------------------------------------------------------------

const KIND_NAME = { weekly: "Week", monthly: "Month", quarterly: "Quarter" };

views.archive = async (id) => {
  const list = await api("/api/overviews");
  if (!list.length) return `<div class="page"><header class="head"><h1>Reviews</h1>
    <p class="voice small">Each Sunday at 8pm I'll look back at your week here. Months on their last day, quarters when the term ends.</p></header></div>`;
  id = Number(id) || list[0].id;
  const o = await api(`/api/overviews/${id}`);
  const rows = (xs, f) => xs.map(f).join("") || `<p class="empty">None.</p>`;
  return `<div class="reviews">
    <aside><h2 style="margin-bottom:8px">Reviews</h2>${list.map(x => `<a href="#archive/${x.id}" class="${x.id === id ? "on" : ""}">
      ${KIND_NAME[x.kind]} of ${esc(fmtDay(x.period_start).replace(/^\w+, /, ""))}</a>`).join("")}</aside>
    <article class="page" style="max-width:none">
      <header class="head"><div class="dateline">${esc(fmtDay(o.period_start))} – ${esc(fmtDay(o.period_end))}</div>
        <h1>Your ${KIND_NAME[o.kind].toLowerCase()}</h1><p class="voice">${esc(o.assessment)}</p></header>
      <section><h2>Time spent</h2>${rows(o.hours, h => `<div class="when-row"><span class="when">${h.hours} h</span><span class="what">${esc(h.name)}</span></div>`)}</section>
      ${o.record ? `<section><h2>What you did this quarter</h2>${o.record.map(g => `<h2 style="font-weight:500;margin-top:8px">${esc(g.goal)}</h2>${g.done.map(x => `<div class="item"><span class="title">${esc(x)}</span></div>`).join("")}`).join("") || `<p class="empty">Nothing recorded.</p>`}</section>`
        : `<section><h2>Done <span class="meta">${o.completed.length}</span></h2>${rows(o.completed, x => `<div class="item"><span class="title">${esc(x.title)}</span><span class="meta">${esc(x.goal)}</span></div>`)}</section>
           <section><h2>Slipped <span class="meta">${o.slipped.length}</span></h2>${rows(o.slipped, x => `<div class="when-row"><span class="when">${esc(fmtDay(x.do_date))}</span><span class="what">${esc(x.title)}</span></div>`)}</section>`}
      ${o.goals ? `<section><h2>Goals</h2>${rows(o.goals, g => `<div class="when-row"><span class="when">${g.done} of ${g.total}</span><span class="what">${esc(g.goal)}</span></div>`)}</section>` : ""}
      ${o.stalled_goals.length ? `<section><h2>No movement yet</h2>${o.stalled_goals.map(g => `<div class="item"><span class="title">${esc(g)}</span></div>`).join("")}</section>` : ""}
      ${o.next ? `<section><h2>Next week</h2>${rows(o.next, x => `<div class="when-row"><span class="when">${esc(fmtDay(x.at))}</span><span class="what">${esc(x.title)}</span></div>`)}</section>` : ""}
    </article></div>`;
};

// ---- Settings ----------------------------------------------------------------

async function saveCanvas(e) {
  e.preventDefault();
  try {
    await send("PUT", "/api/canvas", { url: e.target.elements.url.value.trim() });
    const r = await api("/api/canvas/fetch", { method: "POST" });
    toast(r.new ? `Connected. ${r.new} new from Bruin Learn in <a href="#inbox">Suggestions</a>.` : "Connected. Nothing new right now.");
  } catch (err) { toast(esc(detail(err))); }
  render();
}

async function fetchCanvas(button) {
  button.disabled = true;
  try { const r = await api("/api/canvas/fetch", { method: "POST" }); toast(`${r.new} new, ${r.changed} changed, ${r.removed} removed.`); }
  catch (err) { toast(esc(detail(err))); }
  render();
}

views.settings = async () => {
  const [c, h] = await Promise.all([api("/api/canvas"), api("/api/health")]);
  const status = !c.connected ? "" : c.status === "error"
    ? `<p class="detail" style="color:#8E3B2E">The link stopped working (${esc(c.error || "")}). Paste a new one below.</p>`
    : `<p class="detail">Connected (${esc(c.link)}). I check it every 3 hours${c.checked ? `, last at ${esc(fmtWhen(c.checked))}` : ""}.</p>
       <div class="row-actions"><button class="btn small" onclick="fetchCanvas(this)">Check now</button>
       <button class="btn small quiet" onclick='api("/api/canvas", {method: "DELETE"}).then(render)'>Disconnect</button></div>`;
  return `<div class="page">
    <header class="head"><h1>Settings</h1></header>
    <section class="card"><h2>Bruin Learn calendar</h2>
      <p class="detail">New and changed assignments come to Suggestions. In Bruin Learn: Calendar → Calendar Feed, copy the link. It works like a password, so it stays on this PC.</p>
      ${status}
      <form class="inline" onsubmit="saveCanvas(event)"><label class="sr" for="feed">Feed link</label>
        <input id="feed" name="url" type="url" placeholder="https://bruinlearn.ucla.edu/feeds/calendars/….ics" required>
        <button class="btn ${c.connected ? "" : "primary"}">${c.connected ? "Replace link" : "Connect"}</button></form></section>
    ${pushSection()}
    <section class="card"><h2>The assistant</h2>
      <p class="detail">Chat runs on ${esc(h.ai.model)} ${h.ai.ready ? "(ready)" : `(${esc(h.ai.message)})`}; reading documents uses the larger model when it's downloaded. Everything runs on this PC.</p></section>
    <section class="card"><h2>Development</h2>
      <p class="detail">Start over: removes courses, plans, suggestions, questions, chat, uploads, notes and the Bruin Learn link. A backup of the database is kept first. Notifications on your devices keep working.</p>
      <div class="row-actions"><button class="btn small" onclick="clearAll(this)">Clear everything</button></div></section>
  </div>`;
};

// Development only: delete with app/dev.py.
async function clearAll(button) {
  if (!confirm("Clear everything in Almanac? A backup of the database is kept, but the app starts empty.")) return;
  button.disabled = true;
  try {
    const r = await api("/api/dev/clear-all", { method: "POST" });
    toast(`Cleared. Backup: ${esc(r.backup)}`);
  } catch (e) { toast(esc(detail(e))); }
  refreshBadges(); render();
}

// ---- push (the iPhone Home Screen app, a laptop) ------------------------------

const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const pushSupported = "serviceWorker" in navigator && "PushManager" in window;
const pushOn = () => { try { return localStorage.getItem("pushOn") === "1"; } catch { return false; } };

function pushSection() {
  let body;
  if (isIOS && !standalone) body = `<p class="detail">On iPhone, notifications work from the Home Screen app: tap <b>Share</b>, then <b>Add to Home Screen</b>, open Almanac from there and come back here.</p>`;
  else if (!pushSupported) body = `<p class="detail">This browser can't receive notifications when Almanac is closed. Open windows still show them.</p>`;
  else if (pushOn()) body = `<p class="detail">On for this device.</p><div class="row-actions"><button class="btn small" onclick="testPush(this)">Send a test</button>
      <button class="btn small quiet" onclick="pushOff()">Turn off</button></div>`;
  else body = `<p class="detail">The morning note, check-ins and reminders, even when Almanac is closed.</p>
      <div class="row-actions"><button class="btn primary" onclick="pushOnDevice(this)">Turn on notifications</button></div>`;
  return `<section class="card"><h2>Notifications on this device</h2>${body}</section>`;
}

const b64ToBytes = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));

async function pushOnDevice(button) {
  button.disabled = true;
  try {
    if (await Notification.requestPermission() !== "granted") throw new Error("Notifications weren't allowed. You can allow them in this device's settings.");
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
    await send("POST", "/api/push/subscribe", sub.toJSON());
    try { localStorage.setItem("pushOn", "1"); } catch { }
    await api("/api/push/test", { method: "POST" });
    toast("Notifications are on. A test is on its way.");
  } catch (e) { toast(esc(e.message || String(e))); }
  render();
}

async function pushOff() {
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    const sub = await reg?.pushManager.getSubscription();
    if (sub) { await send("POST", "/api/push/unsubscribe", { endpoint: sub.endpoint }); await sub.unsubscribe(); }
  } catch { }
  try { localStorage.removeItem("pushOn"); } catch { }
  render();
}

async function testPush(button) {
  button.disabled = true;
  await api("/api/push/test", { method: "POST" });
  toast("Sent. It should arrive in a few seconds.");
  render();
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { });

// ---- the frame ---------------------------------------------------------------

function toggleSheet(open) {
  const s = $("#sheet");
  s.hidden = open === undefined ? !s.hidden : !open;
  $("#tabs .more").setAttribute("aria-expanded", String(!s.hidden));
}
$("#sheet").addEventListener("click", e => { if (e.target.id === "sheet" || e.target.closest("a")) toggleSheet(false); });

async function refreshBadges() {
  try {
    const [{ count }, { questions }] = await Promise.all([api("/api/inbox"), api("/api/chat/badge")]);
    $$("[data-badge=inbox]").forEach(b => { b.textContent = count || ""; b.hidden = !count; });
    $$("[data-badge=inbox-dot]").forEach(b => b.hidden = !count);
    $$("[data-badge=chat]").forEach(b => b.hidden = !questions);
  } catch { }
}

// Renders can overlap (a reply arriving while the page checks for changes): only
// the newest one is drawn, so an older one's data never lands on top of it.
let renderSeq = 0, latestRender = null;
function render() { return latestRender = drawView(++renderSeq); }

async function drawView(n) {
  toggleSheet(false);
  refreshBadges();
  const route = location.hash.slice(1) || "today";
  const [name, arg] = route.split("/");
  $$("[data-view]").forEach(a => a.classList.toggle("active", a.dataset.view === route || a.dataset.view === name));
  // the version before the data: a change made while loading is still newer than what's seen
  const version = await planVersion();
  let html;
  try {
    html = await (views[name] || views.today)(arg);
  } catch (e) {
    html = `<div class="page"><div class="notice">I couldn't load this page: ${esc(e.message)}</div></div>`;
  }
  if (n !== renderSeq) return latestRender;  // a newer render started: wait for it instead
  $("#view").innerHTML = html;
  seenVersion = version;
}

// ---- staying current -------------------------------------------------------------
// The server's version changes whenever the plan (or suggestions, questions,
// chat) does: a change made on the phone shows on the open desktop page within
// a few seconds. Never while typing or editing, and the scroll position stays.

let seenVersion = null;
const planVersion = () => api("/api/version").then(r => r.v).catch(() => seenVersion);
const busy = () => !!(sending || /^#(record|follow)/.test(location.hash) || $("#say")?.value ||$("#editor")?.open || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName));

async function stayCurrent() {
  if (document.visibilityState !== "visible" || seenVersion === null) return;
  const v = await planVersion();
  if (v === seenVersion || busy()) return;
  const y = scrollY;
  await render();
  if (!location.hash.startsWith("#chat")) scrollTo(0, y);
}
setInterval(stayCurrent, 5000);
document.addEventListener("visibilitychange", stayCurrent);

// ---- timer -------------------------------------------------------------------

async function startTimer(id) { await api(`/api/tasks/${id}/timer/start`, { method: "POST" }); showTimer(); }
async function stopTimer() {
  const r = await api("/api/timer/stop", { method: "POST" });
  toast(`Stopped: ${r.minutes} min this time, ${r.spent_min} min on it so far.`);
  showTimer(); render();
}
async function keepTimer() { await api("/api/timer/keep", { method: "POST" }); showTimer(); }

async function showTimer() {
  let t = null;
  try { t = await api("/api/timer"); } catch { }
  const el = $("#timer");
  el.hidden = !t;
  if (!t) return;
  const m = t.elapsed_min;
  el.innerHTML = `<span class="live"></span><span class="what">${esc(t.task.title)}</span>
    <span class="elapsed">${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}</span>
    ${t.asking ? `<button class="btn small" onclick="keepTimer()">Still going</button>` : ""}
    <button class="btn small" onclick="stopTimer()">Stop</button>`;
}
setInterval(showTimer, 30000);
showTimer();

// ---- notifications -------------------------------------------------------------
// The server keeps a list; each device remembers the last one it showed.

async function pollNotifications() {
  let seen = null;
  try { seen = localStorage.getItem("seenNotification"); } catch { }
  try {
    const list = await api(`/api/notifications?after=${seen ?? 0}`);
    if (seen !== null) {
      for (const n of list) {
        // on this PC the tray icon pops notifications; a device with push gets them pushed
        const local = ["localhost", "127.0.0.1"].includes(location.hostname);
        if (!local && !pushOn() && "Notification" in window && Notification.permission === "granted") {
          const note = new Notification(n.title, { body: n.body || "", tag: `almanac-${n.id}` });
          note.onclick = () => { window.focus(); location.hash = n.url || "#today"; };
        } else toast(`<b>${esc(n.title)}</b><br>${esc(n.body || "")}${n.url ? ` <a href="${esc(n.url)}">Open</a>` : ""}`);
      }
    }
    const last = list.length ? list[list.length - 1].id : seen ?? (await api("/api/notifications?after=0")).slice(-1)[0]?.id ?? 0;
    try { localStorage.setItem("seenNotification", String(last)); } catch { }
    if (list.length) refreshBadges();
  } catch { }
}
setInterval(pollNotifications, 30000);
pollNotifications();

addEventListener("hashchange", render);
render();
