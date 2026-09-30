const $ = (sel, root = document) => root.querySelector(sel);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
};
const send = (method, path, body) => api(path, { method, body: JSON.stringify(body) });

// ---- formatting -------------------------------------------------------------

const TZ = "America/Los_Angeles";
const asDate = s => new Date(s.length === 10 ? s + "T12:00" : s);  // local wall-clock strings
const fmtDay = s => asDate(s).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
const fmtTime = s => s.length > 10 ? asDate(s).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "";
const fmtWhen = (s, win) => win ? `week of ${fmtDay(win.slice(0, 10))} (day not stated)` : s ? `${fmtDay(s)}${s.length > 10 ? " " + fmtTime(s) : ""}` : "";

let lookups = { courses: [], goals: [], projects: [] };
const courseName = id => { const c = lookups.courses.find(c => c.id === id); return c ? `${c.number} · ${c.instructor.split(" ").pop()}` : ""; };
const tag = (id) => id ? `<span class="tag">${esc(courseName(id))}</span>` : "";
const prov = x => x.provisional ? `<span class="tag prov" title="Provisional in its source">provisional</span>` : "";

async function loadLookups() {
  const [courses, goals, projects] = await Promise.all(["courses", "goals", "projects"].map(k => api(`/api/${k}`)));
  lookups = { courses, goals, projects };
}

// ---- item forms --------------------------------------------------------------

const KINDS = {
  goals: { one: "Goal", fields: [["title", "text", "Title"], ["why", "text", "Why"], ["horizon", ["", "quarter", "year", "multi-year"], "Horizon"]] },
  projects: { one: "Project", fields: [["title", "text", "Title"], ["goal_id", "goals", "Goal"], ["course_id", "courses", "Course"],
    ["deadline", "datetime", "Deadline"], ["team", "check", "Team project"], ["notes", "area", "Notes"]] },
  tasks: { one: "Task", fields: [["title", "text", "Title"], ["project_id", "projects", "Project"], ["course_id", "courses", "Course"],
    ["due", "datetime", "Due"], ["do_date", "date", "Do date"], ["work_kind", ["", "paper", "slides", "other"], "Work kind"],
    ["size", "number", "Size (pages, slides…)"], ["notes", "area", "Notes"]] },
  events: { one: "Event", fields: [["title", "text", "Title"], ["course_id", "courses", "Course"], ["start", "datetime", "Start"],
    ["end", "datetime", "End"], ["repeat", "days", "Repeats weekly on"], ["until", "date", "Until"], ["location", "text", "Location"]] },
  deadlines: { one: "Deadline", fields: [["title", "text", "Title"], ["course_id", "courses", "Course"], ["project_id", "projects", "Project"], ["due", "datetime", "Due"]] },
  courses: { one: "Course", fields: [["number", "text", "Number (e.g. CS 239)"], ["instructor", "text", "Instructor"], ["title", "text", "Title"]] },
  terms: { one: "Term", fields: [["name", "text", "Name"], ["starts", "date", "Quarter begins"], ["instruction_begins", "date", "Instruction begins"],
    ["week1", "date", "Monday of Week 1"], ["instruction_ends", "date", "Instruction ends"], ["finals_start", "date", "Finals begin"],
    ["ends", "date", "Quarter ends"], ["holidays", "area", "Holidays (one per line: YYYY-MM-DD name)"]] },
};
const DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];

function input([name, type, label], v) {
  v = v ?? "";
  let el;
  if (Array.isArray(type)) el = `<select name="${name}">${type.map(o => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  else if (lookups[type]) el = `<select name="${name}" data-int><option value="">—</option>${lookups[type].map(o =>
    `<option value="${o.id}" ${o.id === v ? "selected" : ""}>${esc(o.title || courseName(o.id))}</option>`).join("")}</select>`;
  else if (type === "area") el = `<textarea name="${name}" rows="3">${esc(v)}</textarea>`;
  else if (type === "check") return `<label class="check"><input type="checkbox" name="${name}" ${v ? "checked" : ""}> ${label}</label>`;
  else if (type === "days") el = `<span class="days">${DAYS.map(d => `<label><input type="checkbox" name="${name}" value="${d}" ${v.includes(d) ? "checked" : ""}>${d}</label>`).join("")}</span>`;
  else if (type === "datetime") el = `<span class="dt"><input type="date" name="${name}" value="${v.slice(0, 10)}"><input type="time" name="${name}__t" value="${v.slice(11, 16)}"></span>`;
  else el = `<input type="${type}" name="${name}" value="${esc(v)}" ${type === "number" ? 'step="any"' : ""}>`;
  return `<label>${label}${el}</label>`;
}

function readForm(root, kind) {  // root: a form or any element holding the inputs
  const out = {};
  for (const [name, type] of KINDS[kind].fields) {
    const el = root.querySelector(`[name="${name}"]`);
    if (!el) continue;
    if (type === "check") out[name] = el.checked;
    else if (type === "days") out[name] = [...root.querySelectorAll(`[name=${name}]:checked`)].map(c => c.value).join(",") || null;
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
    ${k.fields.map(f => input(f, v[f[0]])).join("")}
    <p class="error" hidden></p>
    <div class="actions">
      ${item ? `<button type="button" class="danger" data-act="delete">Delete</button>` : ""}
      <span class="grow"></span>
      <button type="button" data-act="cancel">Cancel</button>
      <button class="primary">Save</button>
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
    } catch (err) { const p = $(".error", form); p.hidden = false; p.textContent = err.message; }
  });
  dlg.showModal();
}

async function toggleTask(id, done) {
  await send("PATCH", `/api/tasks/${id}`, { status: done ? "done" : "open" });
  render();
}

// ---- rows --------------------------------------------------------------------

const taskRow = t => `<li class="row ${t.status === "done" ? "done" : ""}">
  <input type="checkbox" ${t.status === "done" ? "checked" : ""} onchange="toggleTask(${t.id}, this.checked)">
  <a class="title" onclick='edit("tasks", ${t.id})'>${esc(t.title)}</a>${tag(t.course_id)}${prov(t)}
  <span class="meta">${t.due ? "due " + esc(fmtWhen(t.due, t.window)) : ""}</span></li>`;
const eventRow = e => `<li class="row"><span class="time">${esc(fmtTime(e.start))}</span>
  <a class="title" onclick='edit("events", ${e.id})'>${esc(e.title)}</a>${tag(e.course_id)}${prov(e)}
  <span class="meta">${e.end ? "until " + esc(fmtTime(e.end)) : ""}${e.location ? " · " + esc(e.location) : ""}</span></li>`;
const deadlineRow = d => `<li class="row"><span class="time">${esc(fmtTime(d.due) || "all day")}</span>
  <a class="title" onclick='edit("deadlines", ${d.id})'>${esc(d.title)}</a>${tag(d.course_id)}${prov(d)}</li>`;
const section = (title, rows, empty) => `<section><h3>${title}</h3>${rows.length ? `<ul>${rows.join("")}</ul>` : `<p class="empty">${empty}</p>`}</section>`;

async function edit(kind, id) { openEditor(kind, await api(`/api/${kind}/${id}`)); }

// ---- views -------------------------------------------------------------------

const views = {
  async today() {
    const [h, t] = await Promise.all([api("/api/health"), api("/api/today"), loadLookups()]);
    const date = asDate(t.date).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    return `
      <header class="head"><div><h1>Today</h1><p class="sub">${esc(date)}</p></div>
        <button class="primary" onclick='openEditor("tasks", null, {do_date: "${t.date}"})'>Add task</button></header>
      ${h.ai.ready ? "" : `<div class="notice">The assistant is unavailable: ${esc(h.ai.message)}</div>`}
      ${t.overdue.length ? section("Carried over", t.overdue.map(taskRow), "") : ""}
      ${section("To do today", t.tasks.map(taskRow), "Nothing planned for today.")}
      ${section("Schedule", t.events.map(eventRow), "No events today.")}
      ${t.deadlines.length ? section("Due today", t.deadlines.map(deadlineRow), "") : ""}
      ${t.done.length ? section("Done", t.done.map(taskRow), "") : ""}`;
  },

  async plan() {
    const tab = sessionStorage.getItem("planTab") || "tasks";
    const [items] = await Promise.all([api(`/api/${tab}`), loadLookups()]);
    const describe = {
      tasks: taskRow,
      events: e => `<li class="row"><a class="title" onclick='edit("events", ${e.id})'>${esc(e.title)}</a>${tag(e.course_id)}${prov(e)}
        <span class="meta">${e.repeat ? `${esc(e.repeat.replaceAll(",", "/"))} ${esc(fmtTime(e.start))}` : esc(fmtWhen(e.start, e.window))}</span></li>`,
      deadlines: d => `<li class="row"><a class="title" onclick='edit("deadlines", ${d.id})'>${esc(d.title)}</a>${tag(d.course_id)}${prov(d)}
        <span class="meta">${esc(fmtWhen(d.due, d.window)) || "date unknown"}</span></li>`,
      projects: p => `<li class="row"><a class="title" onclick='edit("projects", ${p.id})'>${esc(p.title)}</a>${tag(p.course_id)}
        <span class="meta">${p.deadline ? "by " + esc(fmtWhen(p.deadline)) : ""}</span></li>`,
      goals: g => `<li class="row"><a class="title" onclick='edit("goals", ${g.id})'>${esc(g.title)}</a>
        <span class="meta">${esc(g.horizon || "")}</span></li>`,
      courses: c => `<li class="row"><a class="title" onclick='edit("courses", ${c.id})'>${esc(c.number)} · ${esc(c.instructor)}</a>
        <span class="meta">${esc(c.title || "")}</span></li>`,
      terms: t => `<li class="row"><a class="title" onclick='edit("terms", ${t.id})'>${esc(t.name)}</a>
        <span class="meta">Week 1 = ${esc(fmtDay(t.week1))} · classes end ${esc(fmtDay(t.instruction_ends))}</span></li>`,
    }[tab];
    return `
      <header class="head"><h1>Plan</h1><button class="primary" onclick='openEditor("${tab}")'>Add ${KINDS[tab].one.toLowerCase()}</button></header>
      <div class="tabs">${Object.keys(KINDS).map(k =>
        `<button class="${k === tab ? "on" : ""}" onclick='sessionStorage.setItem("planTab", "${k}"); render()'>${KINDS[k].one}s</button>`).join("")}</div>
      ${items.length ? `<ul>${items.map(describe).join("")}</ul>` : `<p class="empty">No ${KINDS[tab].one.toLowerCase()}s yet.</p>`}`;
  },
};

// ---- calendar ----------------------------------------------------------------

const cal = { mode: sessionStorage.getItem("calMode") || "week", anchor: null };
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const monday = d => addDays(d, -((d.getDay() + 6) % 7));
const courseColor = id => lookups.courses.find(c => c.id === id)?.color || "var(--muted)";

function chip(kind, x) {
  const color = courseColor(x.course_id);
  const label = (x.window ? "Wk · " : "") + (kind === "events" ? `${fmtTime(x.start)} ${x.title}` : kind === "deadlines" ? `⚑ ${x.title}` : x.title);
  const cls = ["chip", kind, x.provisional ? "prov" : "", x.status === "done" ? "done" : "", x.unscheduled ? "unsched" : ""].join(" ");
  const drag = kind === "tasks" ? `draggable="true" ondragstart="event.dataTransfer.setData('text/plain', ${x.id})"` : "";
  const title = [x.title, courseName(x.course_id), x.window ? "sometime this week, day not stated" : "", x.provisional ? "provisional" : "", x.unscheduled ? "no do date yet (shown on due day)" : ""].filter(Boolean).join(" · ");
  return `<div class="${cls}" style="--c:${color}" ${drag} title="${esc(title)}" onclick='edit("${kind}", ${x.id})'>${esc(label)}</div>`;
}

async function dropTask(e, day) {
  e.preventDefault();
  e.currentTarget.classList.remove("over");
  await send("PATCH", `/api/tasks/${e.dataTransfer.getData("text/plain")}`, { do_date: day });
  render();
}

function calNav(step) {
  const a = cal.anchor;
  cal.anchor = step === 0 ? null : cal.mode === "week" ? addDays(a, 7 * step) : new Date(a.getFullYear(), a.getMonth() + step, 1);
  render();
}

views.calendar = async () => {
  const today = asDate((await api("/api/today")).date);
  cal.anchor ??= today;
  const a = cal.anchor;
  const first = cal.mode === "week" ? monday(a) : monday(new Date(a.getFullYear(), a.getMonth(), 1));
  const days = cal.mode === "week" ? 7 : Math.ceil(((new Date(a.getFullYear(), a.getMonth() + 1, 0) - first) / 864e5 + 1) / 7) * 7;
  const [data] = await Promise.all([api(`/api/calendar?start=${iso(first)}&end=${iso(addDays(first, days - 1))}`), loadLookups()]);
  const by = {};
  const put = (day, html) => (by[day] ??= []).push(html);
  data.events.forEach(e => put(e.start.slice(0, 10), chip("events", e)));
  data.deadlines.forEach(d => put(d.due.slice(0, 10), chip("deadlines", d)));
  data.tasks.forEach(t => put(t.do_date, chip("tasks", t)));
  data.unscheduled.forEach(t => put(t.due.slice(0, 10), chip("tasks", { ...t, unscheduled: true })));
  const title = cal.mode === "week"
    ? `${fmtDay(iso(first))} – ${fmtDay(iso(addDays(first, 6)))}`
    : a.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const cells = Array.from({ length: days }, (_, i) => {
    const d = addDays(first, i), day = iso(d);
    const out = cal.mode === "month" && d.getMonth() !== a.getMonth();
    return `<div class="day ${day === iso(today) ? "today" : ""} ${out ? "out" : ""}"
      ondragover="event.preventDefault(); this.classList.add('over')" ondragleave="this.classList.remove('over')" ondrop="dropTask(event, '${day}')">
      <div class="dnum">${cal.mode === "week" ? d.toLocaleDateString("en-US", { weekday: "short" }) + " " : ""}${d.getDate()}</div>
      ${(by[day] || []).join("")}</div>`;
  }).join("");
  const legend = lookups.courses.map(c => `<span class="legend" style="--c:${c.color}">${esc(c.number)} · ${esc(c.instructor)}</span>`).join("");
  return `
    <header class="head"><h1>${esc(title)}</h1>
      <div class="calbar">
        <button onclick="calNav(-1)" aria-label="Previous">‹</button><button onclick="calNav(0)">Today</button><button onclick="calNav(1)" aria-label="Next">›</button>
        <span class="tabs">${["week", "month"].map(m => `<button class="${m === cal.mode ? "on" : ""}" onclick='cal.mode="${m}"; sessionStorage.setItem("calMode", "${m}"); render()'>${m[0].toUpperCase() + m.slice(1)}</button>`).join("")}</span>
      </div></header>
    ${legend ? `<p class="legends">${legend}</p>` : ""}
    <div class="grid ${cal.mode}">${cal.mode === "month" ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(d => `<div class="dow">${d}</div>`).join("") : ""}${cells}</div>
    <p class="hint">Drag a task to another day to change its do date. Dashed = provisional; faded = no do date yet.</p>`;
};

// ---- inbox -------------------------------------------------------------------

const isRef = v => typeof v === "string" && /^\$(p\d+\.)?\d+$/.test(v);

function describeOp(o, inbox) {
  const k = KINDS[o.kind], d = o.data || {};
  if (o.op === "delete") return `Delete ${k.one.toLowerCase()} #${o.id}`;
  const verb = o.op === "create" ? "New" : "Change";
  const name = (o.kind === "courses" && d.number ? `${d.number} · ${d.instructor || "?"}` : d.title) || `#${o.id}`;
  const when = d.do_date ? `do ${fmtDay(d.do_date)}` : d.due ? `due ${fmtWhen(d.due, d.window)}` : d.start ? (d.repeat ? `${d.repeat.replaceAll(",", "/")} ${fmtTime(d.start)}${d.end ? "–" + fmtTime(d.end) : ""} until ${fmtDay(d.until)}${d.skip ? `, not ${d.skip.split(",").map(fmtDay).join(", ")}` : ""}` : fmtWhen(d.start, d.window)) : d.deadline ? `by ${fmtWhen(d.deadline)}` : "";
  const course = typeof d.course_id === "number" ? courseName(d.course_id) : isRef(d.course_id) ? "course pending above" : "";
  const changed = o.op === "update" ? Object.keys(d).join(", ") : "";
  return `<span class="opverb">${verb} ${k.one.toLowerCase()}</span> <b>${esc(name)}</b>
    ${[when, course, changed && "changes " + changed].filter(Boolean).map(s => `<span class="meta-inline">${esc(s)}</span>`).join("")}
    ${d.provisional ? prov(d) : ""}`;
}

async function refreshBadge() {
  try {
    const [{ count }, { questions }] = await Promise.all([api("/api/inbox"), api("/api/chat/badge")]);
    for (const [view, n] of [["inbox", count], ["chat", questions]]) {
      const b = $(`#nav [data-view=${view}] .badge`);
      b.textContent = n || "";
      b.hidden = !n;
    }
  } catch { }
}

function toast(text) {
  const t = $("#toast");
  t.innerHTML = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.hidden = true, 7000);
}
const detail = e => { try { return JSON.parse(e.message.replace(/^\d+ /, "")).detail; } catch { return e.message; } };

async function proposalAction(id, action) {
  try {
    await api(`/api/proposals/${id}/${action}`, { method: "POST" });
  } catch (e) { toast(esc(detail(e))); }
  render();
}

async function acceptAll(sourceId) {
  const r = await api(`/api/sources/${sourceId}/accept-all`, { method: "POST" });
  if (r.skipped.length) toast(`Accepted ${r.accepted}. Skipped:<br>` + r.skipped.map(s => `• ${esc(s.summary)}: ${esc(s.reason)}`).join("<br>"));
  render();
}

let inboxCache = [];
async function editProposal(id) {
  await loadLookups();
  const p = inboxCache.find(p => p.id === id);
  const dlg = $("#editor");
  dlg.innerHTML = `<form method="dialog"><h2>Edit before accepting</h2>
    ${p.quote ? `<blockquote>${esc(p.quote)}</blockquote>` : ""}
    ${p.ops.map((o, i) => o.op === "delete" ? `<p>${describeOp(o)}</p>` : `<fieldset data-i="${i}"><legend>${esc(KINDS[o.kind].one)}</legend>
      ${KINDS[o.kind].fields.filter(f => !isRef(o.data?.[f[0]]) && (o.op === "create" || f[0] in o.data)).map(f => input(f, o.data?.[f[0]])).join("")}</fieldset>`).join("")}
    <p class="error" hidden></p>
    <div class="actions"><span class="grow"></span><button type="button" data-act="cancel">Cancel</button><button class="primary">Accept</button></div></form>`;
  const form = $("form", dlg);
  $("[data-act=cancel]", form).onclick = () => dlg.close();
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
    catch (err) { const el = $(".error", form); el.hidden = false; el.textContent = err.message; }
  };
  dlg.showModal();
}

async function uploadFiles(files, replaces = null) {
  for (const f of files) {
    const body = new FormData();
    body.append("file", f);
    const r = await fetch(`/api/uploads${replaces ? `?replaces=${replaces}` : ""}`, { method: "POST", body });
    if (!r.ok) toast(esc(`${f.name}: ${await r.text()}`));
  }
  render();
}

const uploadRow = s => {
  const status = s.status === "processing" ? `<span class="spin"></span> Reading…`
    : s.status === "failed" ? `<span class="bad">Failed</span>` : "Done";
  const dropped = s.dropped.length ? `<details><summary>${s.dropped.length} item${s.dropped.length > 1 ? "s" : ""} dropped</summary>
    <ul>${s.dropped.map(d => `<li><b>${esc(d.title)}</b>: ${esc(d.reason)}<blockquote>${esc(d.quote || "")}</blockquote></li>`).join("")}</ul></details>` : "";
  const again = s.status === "processing" ? "" : `<label class="linkish" title="Upload an updated copy: only changes will be proposed">New version
    <input type="file" accept=".pdf,.docx,.txt,.md" hidden onchange="uploadFiles(this.files, ${s.id})"></label>`;
  return `<li class="row upload"><span class="title">${esc(s.title)}</span><span class="meta">${status}</span>${again}</li>
    ${s.error ? `<li class="uperror">${esc(s.error)}</li>` : ""}${dropped ? `<li class="updropped">${dropped}</li>` : ""}`;
};

let pollTimer;
views.inbox = async () => {
  const [box, sources] = await Promise.all([api("/api/inbox"), api("/api/sources"), loadLookups()]);
  clearTimeout(pollTimer);
  if (sources.some(s => s.status === "processing")) pollTimer = setTimeout(() => location.hash === "#inbox" && render(), 3000);
  const uploads = `<section class="uploads">
    <label class="drop" ondragover="event.preventDefault(); this.classList.add('over')" ondragleave="this.classList.remove('over')"
      ondrop="event.preventDefault(); this.classList.remove('over'); uploadFiles(event.dataTransfer.files)">
      <input type="file" multiple accept=".pdf,.docx,.txt,.md" hidden onchange="uploadFiles(this.files)">
      <b>Upload a syllabus or document</b><span>PDF, DOCX or TXT. Drop files here or click to choose.</span></label>
    ${sources.length ? `<ul>${sources.slice(0, 5).map(uploadRow).join("")}</ul>` : ""}</section>`;
  inboxCache = box.proposals;
  const ready = box.proposals.filter(p => !p.blocked_by), waiting = box.proposals.filter(p => p.blocked_by);
  const groups = {};
  for (const p of ready) (groups[p.source?.id ?? 0] ??= { source: p.source, items: [] }).items.push(p);
  const card = p => `<li class="card ${p.blocked_by ? "blocked" : ""}">
    <p class="summary">${esc(p.summary)}</p>
    <ul class="ops">${p.ops.map(o => `<li>${describeOp(o)}</li>`).join("")}</ul>
    ${p.quote ? `<blockquote>${esc(p.quote)}</blockquote>` : ""}
    ${p.blocked_by ? `<p class="waiting">Waiting on your answer in <a href="#chat">Chat</a>: ${esc(p.blocked_by)}</p>` : ""}
    <div class="actions">
      <button class="primary" ${p.blocked_by ? "disabled" : ""} onclick="proposalAction(${p.id}, 'accept')">Accept</button>
      <button ${p.blocked_by ? "disabled" : ""} onclick="editProposal(${p.id})">Edit</button>
      <button onclick="proposalAction(${p.id}, 'reject')">Reject</button>
    </div></li>`;
  const proposals = Object.values(groups).map(g => `<section>
      <div class="grouphead"><h3>${esc(g.source?.title || "Other")}</h3>
        ${g.source && g.items.length > 1 ? `<button onclick="acceptAll(${g.source.id})">Accept all ${g.items.length}</button>` : ""}</div>
      <ul>${g.items.map(card).join("")}</ul></section>`).join("");
  const later = waiting.length ? `<details class="later"><summary>${waiting.length} more waiting on your answers in Chat</summary>
    <ul>${waiting.map(card).join("")}</ul></details>` : "";
  return `<h1>Inbox</h1><p class="sub">Nothing changes in your plan until you accept it.</p>
    ${uploads}${proposals || `<p class="empty">Nothing to review.</p>`}${later}`;
};

// ---- chat --------------------------------------------------------------------

async function chatSend(e) {
  e.preventDefault();
  const box = e.target.elements.text, text = box.value.trim();
  if (!text) return;
  box.value = "";
  const log = $(".chatlog");
  log.insertAdjacentHTML("beforeend", `<div class="msg user">${esc(text)}</div><div class="msg assistant typing"><span></span><span></span><span></span></div>`);
  log.scrollTop = log.scrollHeight;
  try { await send("POST", "/api/chat", { text }); } catch (err) { toast(esc(detail(err))); }
  render();
}

async function chatAction(action) {
  await api(`/api/chat/${action}`, { method: "POST" });
  render();
}

// Just enough markdown for chat replies: **bold**, *italic*, `code`, "- " lists.
const md = s => esc(s)
  .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>").replace(/`([^`]+)`/g, "<code>$1</code>")
  .replace(/(^|\n)[-•] (.*)(?=\n|$)/g, "$1<li>$2</li>").replace(/(<li>.*<\/li>)(?!\n?<li>)/gs, "<ul>$1</ul>")
  .replace(/\n/g, "<br>").replace(/<br>(<\/?(ul|li))/g, "$1").replace(/(<\/(ul|li)>)<br>/g, "$1");

views.chat = async () => {
  const c = await api("/api/chat");
  const msgs = c.messages.map(m => `<div class="msg ${m.role}">${m.role === "assistant" ? md(m.text) : esc(m.text).replace(/\n/g, "<br>")}
    ${m.quote && c.current?.id === m.id ? `<blockquote>${esc(m.quote)}</blockquote>` : ""}</div>`).join("");
  const chips = c.current ? `<div class="chips">
      <button onclick="chatAction('skip')">Skip for now</button>
      <button onclick="chatAction('dismiss')">Not relevant to me</button>
      ${c.waiting ? `<span class="meta">${c.waiting} more question${c.waiting > 1 ? "s" : ""} after this</span>` : ""}</div>` : "";
  setTimeout(() => { const l = $(".chatlog"); if (l) l.scrollTop = l.scrollHeight; $("#chatinput")?.focus(); });
  return `<div class="chat">
    <h1>Chat</h1>
    <div class="chatlog">${msgs || `<p class="empty">Tell me what's going on: classes, plans, things you keep meaning to do.</p>`}</div>
    ${chips}
    <form class="chatbar" onsubmit="chatSend(event)">
      <textarea id="chatinput" name="text" rows="1" placeholder="${c.current ? "Your answer…" : "Message Almanac…"}"
        onkeydown="if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.form.requestSubmit(); }"></textarea>
      <button class="primary">Send</button></form></div>`;
};

async function render() {
  refreshBadge();
  const name = location.hash.slice(1) || "today";
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.view === name));
  try {
    $("#view").innerHTML = await (views[name] || views.today)();
  } catch (e) {
    $("#view").innerHTML = `<div class="notice">Couldn't load this page: ${esc(e.message)}</div>`;
  }
}

addEventListener("hashchange", render);
render();
