// Local FPS analysis GUI: upload -> poll progress -> show results. No login, no build step.
const $ = (id) => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);
const LABEL = { freeze: "Freeze", fps_drop: "FPS drop", stutter: "Stutter" };
let file = null, polling = null, cfg = null, current = null;   // current = job shown

const fmtT = (s) => { const m = Math.floor(s / 60); return `${String(m).padStart(2, "0")}:${(s - 60 * m).toFixed(3).padStart(6, "0")}`; };
const esc = (t) => String(t ?? "—").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function init() {
  cfg = await (await fetch("/api/config")).json();
  $("target").value = String(cfg.target_fps);
  $("drop_ratio").value = cfg.drop_ratio; $("freeze_ms").value = cfg.freeze_ms; $("stutter").value = cfg.stutter_min_missed;
  const drop = $("drop");
  drop.onclick = () => $("file").click();
  drop.onkeydown = (e) => (e.key === "Enter" || e.key === " ") && $("file").click();
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); pick(e.dataTransfer.files[0]); };
  $("file").onchange = (e) => pick(e.target.files[0]);
  $("analyze").onclick = start;
  $("again").onclick = $("again2").onclick = reset;
  const fromHash = () => {   // reload-safe and link-safe: #job=<id>
    const m = location.hash.match(/job=([a-f0-9]+)/);
    if (m && m[1] !== current) watch(m[1]);
    else if (!m && current) reset();
  };
  window.onhashchange = fromHash;
  fromHash();
}

function pick(f) {
  $("upload-error").textContent = "";
  if (!f) return;
  if (!/\.(mp4|mkv|avi)$/i.test(f.name)) { $("upload-error").textContent = `"${f.name}" is not supported. Accepted formats: .avi, .mkv, .mp4`; return; }
  if (f.size > cfg.max_upload_mb * 1048576) { $("upload-error").textContent = `File is larger than ${cfg.max_upload_mb} MB`; return; }
  file = f;
  $("drop-title").textContent = f.name;
  $("drop-sub").textContent = `${(f.size / 1048576).toFixed(1)} MB · click to choose another`;
  $("analyze").disabled = false;
}

function start() {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("target_fps", $("target").value);
  fd.append("drop_ratio", $("drop_ratio").value);
  fd.append("freeze_ms", $("freeze_ms").value);
  fd.append("stutter_min_missed", $("stutter").value);
  show("upload", false); show("progress"); $("progress-title").textContent = "Uploading…";
  const x = new XMLHttpRequest();   // XHR for upload progress on large files
  x.open("POST", "/api/analyze");
  x.upload.onprogress = (e) => e.lengthComputable && setBar(0.1 * e.loaded / e.total, `uploading ${(100 * e.loaded / e.total).toFixed(0)}%`);
  x.onload = () => {
    let body = {}; try { body = JSON.parse(x.responseText); } catch { /* */ }
    if (x.status >= 300) return fail(body.detail || x.statusText);
    location.hash = `job=${body.job_id}`;
    watch(body.job_id);
  };
  x.onerror = () => fail("Could not reach the local server. Is `python main.py --gui` still running?");
  x.send(fd);
}

function setBar(f, msg) { $("bar").style.width = `${Math.round(f * 100)}%`; $("progress-msg").textContent = msg; }

function watch(id) {
  current = id;
  show("upload", false); show("progress"); show("results", false); show("failed", false);
  $("progress-title").textContent = "Analysing…";
  clearInterval(polling);
  const tick = async () => {
    const r = await fetch(`/api/jobs/${id}`);
    if (!r.ok) { clearInterval(polling); return fail((await r.json()).detail); }
    const j = await r.json();
    setBar(0.1 + 0.9 * j.progress, `${(j.progress * 100).toFixed(0)}% · ${j.message}`);
    if (j.status === "done") { clearInterval(polling); render(j); }
    if (j.status === "failed") { clearInterval(polling); fail(j.error); }
  };
  tick(); polling = setInterval(tick, 700);
}

function render(j) {
  const r = j.result, e = r.effective_fps, f = r.frame_times, c = r.counts, m = r.metadata;
  show("progress", false); show("results");
  $("r-video").textContent = `${r.video_name} · ${m.resolution} · ${m.duration_s} s`;
  $("r-verdict").textContent = r.verdict;
  $("r-report").href = j.report; $("r-json").href = `/api/jobs/${j.id}/analysis.json`;
  const stat = (n, l) => `<div class="stat"><div class="n">${esc(n)}</div><div class="l">${l}</div></div>`;
  $("r-stats").innerHTML = [
    stat(`${e.median ?? "—"}`, `median effective FPS (target ${e.target_fps})`),
    stat(`${f.one_percent_low_fps ?? "—"}`, "1% low FPS"),
    stat(`${e.min ?? "—"}`, "lowest effective FPS"),
    stat(`${c.freezes} / ${c.fps_drops} / ${c.stutters}`, "freezes / drops / stutters"),
    stat(`${Math.round(e.measurable_fraction * 100)}%`, "of the video measurable"),
    stat(`${m.nominal_fps} → ${m.average_fps}`, "nominal → average FPS"),
  ].join("");
  $("c-eff").src = j.charts.effective_fps; $("c-int").src = j.charts.frame_intervals; $("c-chg").src = j.charts.frame_changes;
  $("r-events").innerHTML = r.events.length ? `<table><thead><tr><th>Type</th><th>Start</th><th>End</th><th>Duration</th><th>What happened</th></tr></thead><tbody>${
    r.events.map((ev) => `<tr><td><span class="tag ${ev.type}">${LABEL[ev.type]}</span></td><td>${fmtT(ev.start_s)}</td><td>${fmtT(ev.end_s)}</td><td>${ev.duration_s.toFixed(2)} s</td><td>${esc(ev.description)}</td></tr>`).join("")
  }</tbody></table><p class="muted small">Watch the video at these times to confirm: video edits and intentional pauses can look like freezes.</p>`
    : `<p>No freezes, FPS drops or stutter periods were detected in the measurable part of the video.</p>`;
  const rows = [["Resolution", m.resolution], ["Duration", `${m.duration_s} s`], ["Frames", m.frame_count.toLocaleString()],
    ["Codec / container", `${m.codec} / ${m.container}`], ["Nominal FPS", m.nominal_fps], ["Average FPS (timestamps)", m.average_fps],
    ["Frame rate type", m.variable_frame_rate ? "variable" : "constant"], ["Frame time p50 / p99", `${f.p50_ms} / ${f.p99_ms} ms`],
    ["Missed frames while moving", c.missed_frames_while_moving], ["Processing", `${r.processing.seconds} s (${r.processing.realtime_factor}× real time)`]];
  $("r-meta").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${esc(v)}</td></tr>`).join("");
  $("r-lim").innerHTML = r.limitations.concat(r.warnings).map((l) => `<li>${esc(l)}</li>`).join("");
  $("r-folder").textContent = `Saved in ${j.folder}`;
}

function fail(msg) {
  show("progress", false); show("upload", false); show("results", false); show("failed");
  $("f-msg").textContent = msg || "Unknown error";
}

function reset() {
  clearInterval(polling); current = null; history.replaceState(null, "", "/");
  file = null; $("file").value = ""; $("analyze").disabled = true;
  $("drop-title").textContent = "Drop a video here or click to choose"; $("drop-sub").textContent = ".mp4 · .mkv · .avi";
  show("results", false); show("failed", false); show("progress", false); show("upload");
}

init();
