// Recording a lecture: the Record page (Start, then Captions while it runs).
// Audio is turned into 16 kHz mono 16-bit samples in the browser and sent to
// the PC a second at a time, each piece numbered; pieces the PC hasn't
// confirmed are kept and sent again, so a dropped connection loses nothing.
// See .scratch/lecture-recording/spec.md.

const KINDS_LECTURE = { paper_session: "Paper session", concept_lecture: "Concept lecture", presentation_day: "Presentation day" };
const rec = { id: null, course: null, kind: null, stream: null, ctx: null, queue: [], seq: 0, pumping: false, paused: false,
              lines: [], partial: "", seconds: 0, unsent: 0, captionsError: null, wake: null, note: "",
              jottings: [], jotAt: null, jotQueue: [] };
const recording = () => rec.id !== null;

// The AudioWorklet: float samples in, 16-bit pieces of one second out.
const WORKLET = URL.createObjectURL(new Blob([`
class PCM16 extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Int16Array(16000); this.n = 0; }
  process(inputs) {
    // No input this quantum (some devices send nothing while it's quiet, or the
    // track is muted): count it as silence, so the audio keeps to real time.
    const ch = inputs[0] && inputs[0][0], n = ch ? ch.length : 128;
    for (let i = 0; i < n; i++) {
      const v = ch ? Math.max(-1, Math.min(1, ch[i])) : 0;
      this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.buffer, [this.buf.buffer]); this.buf = new Int16Array(16000); this.n = 0; }
    }
    return true;
  }
}
registerProcessor("pcm16", PCM16);`], { type: "text/javascript" }));

async function captureAudio(source) {
  let stream;
  if (source === "mic") {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true, autoGainControl: true } });
  } else {
    // Chrome/Edge: pick the tab with the lecture (or the screen) and tick "Share tab audio"
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
                                                            systemAudio: "include", selfBrowserSurface: "exclude" });
    if (!stream.getAudioTracks().length) {
      stream.getTracks().forEach(t => t.stop());
      throw new Error("No audio was shared. Start again, choose the lecture's tab (or the screen) and tick “Share audio”.");
    }
  }
  const ctx = new AudioContext({ sampleRate: 16000 });  // the browser resamples to what the transcriber takes
  await ctx.audioWorklet.addModule(WORKLET);
  const node = new AudioWorkletNode(ctx, "pcm16");
  node.port.onmessage = e => addPiece(e.data);
  const mute = ctx.createGain();
  mute.gain.value = 0;  // pulled through the graph, never played back
  ctx.createMediaStreamSource(new MediaStream(stream.getAudioTracks())).connect(node).connect(mute).connect(ctx.destination);
  stream.getAudioTracks()[0].onended = () => {  // "Stop sharing" in Chrome's bar
    if (!recording()) return;
    rec.paused = true;
    rec.note = "Audio sharing stopped. Resume to choose the audio again, or Stop to finish.";
    releaseCapture();
    drawLive();
  };
  rec.stream = stream;
  rec.ctx = ctx;
  ctx.onstatechange = keepTime;
  startClock();
}

function addPiece(data) {
  if (!rec.paused) { rec.queue.push({ seq: rec.seq++, data }); pump(); }
}

// The audio's clock is the AudioContext's. If the browser or the system
// suspends it (the device sleeping, another app taking the microphone), time
// passes with no audio: fill that time with silence, so the recording's length
// and the jottings' moments match the lecture. A pause by the student isn't
// counted: the clock restarts when they resume.
function startClock() {
  rec.clock = rec.ctx ? { wall: performance.now(), audio: rec.ctx.currentTime, filled: 0 } : null;
}

function keepTime() {
  const ctx = rec.ctx, c = rec.clock;
  if (!recording() || rec.paused || !ctx || !c) return;
  if (ctx.state !== "running") { ctx.resume().catch(() => {}); return; }
  const behind = (performance.now() - c.wall) / 1000 - (ctx.currentTime - c.audio) - c.filled;
  if (behind < 2) return;
  const secs = Math.floor(behind);
  for (let i = 0; i < secs; i++) addPiece(new Int16Array(16000).buffer);
  c.filled += secs;
}
setInterval(keepTime, 5000);

function releaseCapture() {
  rec.stream?.getTracks().forEach(t => t.stop());
  rec.ctx?.close().catch(() => {});
  rec.stream = rec.ctx = rec.clock = null;
}

// Send queued pieces in order; keep any the PC hasn't confirmed and try again.
async function pump() {
  if (rec.pumping || !recording()) return;
  rec.pumping = true;
  while (rec.queue.length && recording()) {
    const piece = rec.queue[0];
    try {
      const r = await fetch(`/api/recordings/${rec.id}/chunk?seq=${piece.seq}&since=${rec.lines.length}`,
                            { method: "POST", body: piece.data, headers: { "Content-Type": "application/octet-stream" } });
      if (r.status === 409) {
        const d = (await r.json()).detail;
        if (typeof d?.next === "number") { rec.queue = rec.queue.filter(p => p.seq >= d.next); continue; }  // it has these already
        stoppedByThePC(typeof d === "string" ? d : "This recording has stopped.");  // auto-stop, or stopped on another device
        break;
      }
      if (!r.ok) throw new Error(String(r.status));
      const s = await r.json();
      rec.queue.shift();
      rec.lines.push(...s.lines);
      Object.assign(rec, { partial: s.partial, seconds: s.seconds, captionsError: s.captions_error, unsent: 0 });
    } catch {
      rec.unsent = rec.queue.length;  // offline for now: keep them, retry
      drawLive();
      await new Promise(res => setTimeout(res, 2000));
      continue;
    }
    drawLive();
  }
  rec.pumping = false;
}

function stoppedByThePC(why) {
  const id = rec.id;
  releaseCapture();
  rec.wake?.release().catch(() => {});
  rec.pip?.close();
  Object.assign(rec, { id: null, queue: [], lines: [], partial: "", pip: null });
  toast(`${esc(why)} The transcript is on its way.`);
  location.hash = `#lecture/${id}`;
}

async function keepAwake() {
  try { rec.wake = await navigator.wakeLock?.request("screen"); } catch { }  // the laptop sleeping would cut the audio
}
document.addEventListener("visibilitychange", () => { if (recording() && document.visibilityState === "visible") keepAwake(); });
addEventListener("beforeunload", e => { if (recording()) { e.preventDefault(); e.returnValue = ""; } });

async function startRecording(form) {
  const f = new FormData(form), source = f.get("source");
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    await captureAudio(source);
  } catch (e) {
    btn.disabled = false;
    toast(esc(e.name === "NotAllowedError" ? "The browser wasn't allowed to record. Allow the microphone or the sharing, then start again." : e.message));
    return;
  }
  try {
    const r = await api("/api/recordings/start", { method: "POST", body: JSON.stringify(
      { course_id: f.get("course") ? Number(f.get("course")) : null, kind: f.get("kind") || null, date: todayIso || undefined }) });
    Object.assign(rec, { id: r.id, course: r.course_id, kind: r.kind, queue: [], seq: 0, lines: [], partial: "", seconds: 0, paused: false, note: "", source,
                         jottings: [], jotAt: null, jotQueue: [] });
  } catch (e) {
    releaseCapture();
    btn.disabled = false;
    toast(esc(detail(e)));
    return;
  }
  keepAwake();
  render();
}

async function resumeRecording(id, source) {
  // after a reload, or after sharing stopped: new audio, same Recording, numbering where the PC left off
  try { await captureAudio(source); } catch (e) { toast(esc(e.message)); return; }
  if (rec.id !== id) {
    const r = await api(`/api/recordings/${id}`), s = await api(`/api/recordings/${id}/live`);
    Object.assign(rec, { id, course: r.course_id, kind: r.kind, queue: [], seq: s.next ?? 0, lines: s.lines, partial: s.partial, seconds: s.seconds,
                         jottings: r.jottings, jotAt: null, jotQueue: [] });
  }
  Object.assign(rec, { paused: false, note: "", source });
  keepAwake();
  render();
}

function pauseRecording() {
  rec.paused = !rec.paused;
  if (rec.paused) { rec.clock = null; rec.ctx?.suspend(); }
  else rec.ctx?.resume().then(startClock);
  drawLive();
}

async function stopRecording() {
  if (!confirm("Stop recording? I'll write the transcript (about a minute per 15 minutes) and delete the audio.")) return;
  const id = rec.id;
  rec.paused = true;
  releaseCapture();
  for (let i = 0; i < 30 && (rec.queue.length || rec.jotQueue.length); i++) { pump(); saveJottings(); await new Promise(res => setTimeout(res, 500)); }  // send what's left
  if (rec.queue.length && !confirm(`${rec.queue.length} seconds of audio haven't reached the PC yet. Stop anyway?`)) { rec.paused = false; return; }
  try { await api(`/api/recordings/${id}/stop`, { method: "POST" }); } catch (e) { toast(esc(detail(e))); }
  rec.wake?.release().catch(() => {});
  rec.pip?.close();
  Object.assign(rec, { id: null, queue: [], lines: [], partial: "", pip: null });
  location.hash = `#lecture/${id}`;
}

// ---- the floating caption window: always on top, over the lecture video (Chrome/Edge) ----

const PIP_STYLE = `
  html, body { margin: 0; height: 100%; background: #1F2A33; color: #F4F1EA; font: 22px/1.4 "Source Sans 3", "Segoe UI", system-ui, sans-serif; }
  #pip { box-sizing: border-box; height: 100%; padding: 10px 16px; overflow: hidden; display: flex; flex-direction: column; justify-content: flex-end; }
  #pip p { margin: 0 0 4px; }
  #pip .partial { color: #A9B4BC; }
  #pip .note { font-size: 14px; color: #A9B4BC; }`;

async function floatCaptions() {
  if (rec.pip) { rec.pip.close(); return; }  // back to the page
  try {
    rec.pip = await documentPictureInPicture.requestWindow({ width: 620, height: 150 });
  } catch (e) { toast(esc(`Couldn't open the caption window: ${e.message}`)); return; }
  const d = rec.pip.document;
  d.title = "Captions";
  d.head.insertAdjacentHTML("beforeend", `<style>${PIP_STYLE}</style>`);
  d.body.innerHTML = `<div id="pip"></div>`;
  rec.pip.addEventListener("pagehide", () => { rec.pip = null; drawLive(); });
  drawLive();
}

function drawPip() {
  const box = rec.pip?.document.getElementById("pip");
  if (!box) return;
  const last = rec.lines.slice(-2).map(l => `<p>${esc(l.text)}</p>`).join("");
  box.innerHTML = last + (rec.partial ? `<p class="partial">${esc(rec.partial)}</p>` : "")
    || `<p class="note">${rec.captionsError ? `Captions aren't available: ${esc(rec.captionsError)}` : "Captions appear here a few seconds after the lecturer speaks."}</p>`;
  if (rec.paused) box.insertAdjacentHTML("beforeend", `<p class="note">${esc(rec.note || "Paused")}</p>`);
}

const mmssLong = s => `${Math.floor(s / 3600) ? Math.floor(s / 3600) + ":" : ""}${String(Math.floor(s / 60) % 60).padStart(Math.floor(s / 3600) ? 2 : 1, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function drawLive() {
  drawPip();
  if ($("#rec-float")) $("#rec-float").textContent = rec.pip ? "Captions here" : "Float captions";
  const bar = $("#rec-status"), box = $("#captions");
  if (!bar || !box) return;
  const status = rec.paused ? (rec.note || "Paused") : rec.unsent ? `Can't reach the PC: ${rec.unsent} s waiting, still recording` : "Recording";
  bar.innerHTML = `<span class="rec-dot ${rec.paused ? "paused" : ""}"></span>${esc(status)} · ${mmssLong(rec.seconds + rec.queue.length)}`;
  $("#rec-pause") && ($("#rec-pause").textContent = rec.paused ? "Resume" : "Pause");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.innerHTML = (rec.lines.map(l => `<p><span class="ts">${mmss(l.start)}</span><span>${esc(l.text)}</span></p>`).join("")
    + (rec.partial ? `<p class="partial"><span class="ts"></span><span>${esc(rec.partial)}</span></p>` : "")) ||
    `<p class="empty">${rec.captionsError ? `Captions aren't available: ${esc(rec.captionsError)} The audio is still being recorded.` : "Captions appear here a few seconds after the lecturer speaks."}</p>`;
  if (rec.captionsError && rec.lines.length) box.insertAdjacentHTML("beforeend", `<p class="empty">Captions paused: ${esc(rec.captionsError)}</p>`);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

// ---- Jottings: stamped with the moment in the lecture (seconds of audio, so pauses don't count) ----

const lectureNow = () => rec.seq;  // one numbered piece per second of recorded audio

function addJotting(mark = false) {
  const box = $("#jot"), text = mark ? "" : box.value.trim();
  const at = mark || !text ? lectureNow() : (rec.jotAt ?? lectureNow());  // when they started typing it
  const j = { key: `${rec.id}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, at, text, saving: true };
  rec.jottings.push(j);
  rec.jottings.sort((a, b) => a.at - b.at);
  rec.jotQueue.push(j);
  if (!mark) box.value = "";
  rec.jotAt = null;
  drawJottings();
  saveJottings();
  box.focus();
}

async function saveJottings() {
  if (rec.savingJots) return;
  rec.savingJots = true;
  while (rec.jotQueue.length && rec.id !== null) {
    const j = rec.jotQueue[0];
    try {
      const saved = await api(`/api/recordings/${rec.id}/jottings`, { method: "POST", body: JSON.stringify({ at: j.at, text: j.text, key: j.key }) });
      Object.assign(j, { id: saved.id, saving: false });
      rec.jotQueue.shift();
    } catch { await new Promise(res => setTimeout(res, 2000)); }  // offline: keep it, try again
  }
  rec.savingJots = false;
  drawJottings();
}

async function deleteJotting(key) {
  const j = rec.jottings.find(x => x.key === key || String(x.id) === String(key));
  if (!j) return;
  rec.jottings = rec.jottings.filter(x => x !== j);
  rec.jotQueue = rec.jotQueue.filter(x => x !== j);
  if (j.id) api(`/api/recordings/${rec.id}/jottings/${j.id}`, { method: "DELETE" }).catch(() => {});
  drawJottings();
}

function drawJottings() {
  const box = $("#jottings");
  if (!box) return;
  box.innerHTML = rec.jottings.map(j => `<div class="jotting ${j.saving ? "saving" : ""}"><span class="ts">${mmss(j.at)}</span>
    <span class="what">${j.text ? esc(j.text) : `<i class="mark">Marked</i>`}</span>
    <button class="icon-btn" onclick="deleteJotting('${j.key || j.id}')" aria-label="Remove" title="Remove">${ICON.x}</button></div>`).join("")
    || `<p class="empty">Your notes go here, each stamped with the moment in the lecture. I'll build the lecture notes on them afterwards.</p>`;
  box.scrollTop = box.scrollHeight;
}

views.record = async (arg) => {
  await loadLookups();
  if (recording()) {
    setTimeout(() => { drawLive(); drawJottings(); $("#jot")?.focus(); });
    const c = lookups.courses.find(c => c.id === rec.course);
    return `<div class="page wide">
      <header class="head"><div class="dateline">${c ? esc(courseName(c.id)) : "Lecture"}${rec.kind ? ` · ${esc(KINDS_LECTURE[rec.kind])}` : ""}</div>
        <div class="rec-bar"><span id="rec-status"></span>
          <button class="btn small" id="rec-pause" onclick="${rec.note ? `resumeRecording(${rec.id}, rec.source)` : "pauseRecording()"}">Pause</button>
          ${"documentPictureInPicture" in window ? `<button class="btn small" id="rec-float" onclick="floatCaptions()">${rec.pip ? "Captions here" : "Float captions"}</button>` : ""}
          <button class="btn primary small" onclick="stopRecording()">Stop</button></div></header>
      <div class="rec-layout">
        <section><h2>Captions <span class="meta">rough, for following along; the transcript replaces them</span></h2><div class="captions" id="captions"></div></section>
        <section><h2>Jottings <span class="meta">Enter on an empty line marks this moment</span></h2>
          <div class="jottings" id="jottings"></div>
          <form class="jot-form" onsubmit="event.preventDefault(); addJotting()">
            <input id="jot" autocomplete="off" placeholder="Type a note, Enter to add" oninput="if (this.value && rec.jotAt === null) rec.jotAt = lectureNow(); if (!this.value) rec.jotAt = null">
            <button type="button" class="btn small" onclick="addJotting(true)" title="This moment matters">Mark</button></form></section>
      </div></div>`;
  }
  const [sug, all] = await Promise.all([api("/api/recordings/suggest"), api("/api/recordings")]);
  const open = all.find(r => r.status === "recording");
  const course = arg ? Number(arg) : sug.course_id;
  const kind = arg && Number(arg) !== sug.course_id ? null : sug.kind;
  return `<div class="page">
    <header class="head"><h1>Record a lecture</h1>
      <p class="voice small">Captions while it runs, then a clean transcript; the audio is deleted once the transcript is written.</p></header>
    ${open ? `<div class="notice">A recording from ${esc(fmtDay(open.date))}${open.course_id ? ` (${esc(courseName(open.course_id))})` : ""} is running.
      <div class="row-actions"><a class="btn primary small" href="#follow/${open.id}">Follow along</a>
        <button class="btn small" onclick="resumeRecording(${open.id}, 'mic')">Resume here with the microphone</button>
        <button class="btn small" onclick="resumeRecording(${open.id}, 'device')">Resume with a tab's audio</button>
        <button class="btn quiet small" onclick="rec.id=${open.id}; stopRecording()">Stop it</button></div></div>` : ""}
    <form class="rec-start" onsubmit="event.preventDefault(); startRecording(this)">
      ${sug.why && !arg ? `<p class="detail">${esc(sug.why)}.</p>` : ""}
      <label>Course <select name="course"><option value="">No course</option>
        ${lookups.courses.map(c => `<option value="${c.id}" ${c.id === course ? "selected" : ""}>${esc(courseName(c.id))}${c.title ? ` · ${esc(c.title)}` : ""}</option>`).join("")}</select></label>
      <label>Lecture <select name="kind"><option value="">Not sure</option>
        ${Object.entries(KINDS_LECTURE).map(([k, v]) => `<option value="${k}" ${k === kind ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <fieldset><legend>Audio</legend>
        <label class="choice"><input type="radio" name="source" value="mic" ${sug.source !== "device" ? "checked" : ""}><span>Microphone<span class="meta">a lecture in the room</span></span></label>
        <label class="choice"><input type="radio" name="source" value="device" ${sug.source === "device" ? "checked" : ""}><span>This device's audio<span class="meta">an online lecture or a replay: choose its tab and tick “Share audio”</span></span></label></fieldset>
      <button type="submit" class="btn primary">Start recording</button>
    </form></div>`;
};

// ---- reading along on another device (the phone): Captions and Jottings, read-only ----

const follow = { id: null, lines: [], timer: null, jottings: [], tick: 0 };

views.follow = async (id) => {
  id = Number(id);
  const r = await api(`/api/recordings/${id}`);
  await loadLookups();
  if (r.status !== "recording") return `<div class="page"><p class="voice">This recording has stopped. <a href="#lecture/${id}">Open the lecture</a>.</p></div>`;
  if (follow.id !== id) Object.assign(follow, { id, lines: [], jottings: r.jottings, tick: 0 });
  clearTimeout(follow.timer);
  setTimeout(pollFollow);
  return `<div class="page wide">
    <header class="head"><div class="dateline">${r.course_id ? esc(courseName(r.course_id)) : "Lecture"}${r.kind_name ? ` · ${esc(r.kind_name)}` : ""}</div>
      <div class="rec-bar"><span id="follow-status"><span class="rec-dot"></span>Following along</span></div></header>
    <div class="rec-layout">
      <section><h2>Captions <span class="meta">read-only; recording on another device</span></h2><div class="captions" id="follow-captions"></div></section>
      <section><h2>Jottings</h2><div class="jottings" id="follow-jottings"></div></section>
    </div></div>`;
};

async function pollFollow() {
  clearTimeout(follow.timer);
  if (!location.hash.startsWith(`#follow/${follow.id}`)) return;  // left the page
  try {
    const s = await api(`/api/recordings/${follow.id}/live?since=${follow.lines.length}`);
    if (s.stopped) { render(); return; }
    follow.lines.push(...s.lines);
    if (follow.tick++ % 4 === 0) follow.jottings = (await api(`/api/recordings/${follow.id}`)).jottings;  // every few seconds
    const box = $("#follow-captions");
    if (box) {
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
      box.innerHTML = follow.lines.map(l => `<p><span class="ts">${mmss(l.start)}</span><span>${esc(l.text)}</span></p>`).join("")
        + (s.partial ? `<p class="partial"><span class="ts"></span><span>${esc(s.partial)}</span></p>` : "")
        || `<p class="empty">${s.captions_error ? `Captions aren't available: ${esc(s.captions_error)}` : "Captions appear here as the lecture goes."}</p>`;
      if (atBottom) box.scrollTop = box.scrollHeight;
      $("#follow-status").innerHTML = `<span class="rec-dot"></span>Following along · ${mmssLong(s.seconds)}`;
    }
    const jb = $("#follow-jottings");
    if (jb) jb.innerHTML = follow.jottings.map(j => `<div class="jotting"><span class="ts">${mmss(j.at)}</span>
      <span class="what">${j.text ? esc(j.text) : `<i class="mark">Marked</i>`}</span></div>`).join("") || `<p class="empty">No jottings yet.</p>`;
  } catch { /* the PC is unreachable for a moment: try again */ }
  follow.timer = setTimeout(pollFollow, 1500);
}

// app.js draws the first page on load; if that was #record before this file arrived, draw it now
if (/^#(record|follow)/.test(location.hash)) render();
