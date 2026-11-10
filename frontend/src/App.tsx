import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiError, CATEGORIES, CATEGORY_LABEL, Category, Detection, DETECTORS, fmtDate, fmtTime, hasToken, Job,
  Project, SEVERITIES, Severity, setToken, User,
} from "./api";

// ------------------------------------------------------------------ routing (hash based)
type Route = { page: "projects" } | { page: "upload" } | { page: "job"; id: string } | { page: "report"; id: string };
function parse(): Route {
  const [, page, id] = window.location.hash.replace(/^#/, "").split("/");
  if (page === "upload") return { page: "upload" };
  if (page === "job" && id) return { page: "job", id };
  if (page === "report" && id) return { page: "report", id };
  return { page: "projects" };
}
const go = (r: string) => { window.location.hash = r; };

export function SeverityBadge({ s }: { s: Severity | null }) {
  if (!s) return <span className="muted small">unrated</span>;
  return <span className={`sev ${s}`}>{s.toUpperCase()}</span>; // colour AND text label (SRS 5.2)
}

function StatusText({ j }: { j: Job }) {
  const label = j.status.replace(/_/g, " ");
  return <span className={`status ${j.status}`}>{label}</span>;
}

// ------------------------------------------------------------------ app shell
export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [route, setRoute] = useState<Route>(parse());
  const [checking, setChecking] = useState(hasToken());

  useEffect(() => {
    const onHash = () => setRoute(parse());
    const onLogout = () => setUser(null);
    window.addEventListener("hashchange", onHash);
    window.addEventListener("gameqa:logout", onLogout);
    if (hasToken()) api.me().then(setUser).catch(() => setUser(null)).finally(() => setChecking(false));
    return () => { window.removeEventListener("hashchange", onHash); window.removeEventListener("gameqa:logout", onLogout); };
  }, []);

  if (checking) return <main className="muted">Loading…</main>;
  if (!user) return <Login onLogin={setUser} />;
  const nav = (p: Route["page"], label: string, hash: string) => (
    <button aria-current={route.page === p ? "page" : undefined} onClick={() => go(hash)}>{label}</button>
  );
  return (
    <>
      <header className="top">
        <h1>Game QA Tester</h1>
        <nav aria-label="Main">{nav("projects", "Projects", "/projects")}{nav("upload", "Upload & queue", "/upload")}</nav>
        <span className="who">{user.email} · {user.role.replace("_", " ")}</span>
        <button className="btn" onClick={() => { setToken(null); setUser(null); }}>Sign out</button>
      </header>
      <main>
        {route.page === "projects" && <Projects user={user} />}
        {route.page === "upload" && <Upload />}
        {route.page === "job" && <Review jobId={route.id} />}
        {route.page === "report" && <Report jobId={route.id} />}
      </main>
    </>
  );
}

// ------------------------------------------------------------------ login (storyboard 8.1)
function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr("");
    try { const r = await api.login(email, password); setToken(r.access_token); onLogin(r.user); }
    catch (x) { setErr(x instanceof ApiError ? x.message : "Sign-in failed"); }
    finally { setBusy(false); }
  };
  return (
    <main>
      <form className="panel login grid" onSubmit={submit} aria-label="Sign in">
        <h2>Sign in to Game QA Tester</h2>
        <label className="field">Email<input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="field">Password<input type="password" autoComplete="current-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {err && <div className="error" role="alert">{err}</div>}
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

// ------------------------------------------------------------------ projects dashboard (8.1)
function Projects({ user }: { user: User }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState("");
  const [name, setName] = useState(""); const [build, setBuild] = useState("");
  const [member, setMember] = useState<Record<string, string>>({});
  const canManage = user.role === "qa_lead" || user.role === "admin";
  const load = useCallback(() => {
    api.projects().then(setProjects).catch((e) => setErr(e.message));
    api.jobs().then(setJobs).catch(() => {});
  }, []);
  useEffect(load, [load]);
  const totals = useMemo(() => {
    const t: Record<string, number> = { high: 0, medium: 0, low: 0 };
    (projects || []).forEach((p) => SEVERITIES.forEach((s) => (t[s] += p.by_severity[s] || 0)));
    return t;
  }, [projects]);
  return (
    <div className="grid cols-2">
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Projects</h2>
          <button className="btn primary" onClick={() => go("/upload")}>Upload a video</button>
        </div>
        {err && <p className="error">{err}</p>}
        {!projects ? <p className="muted">Loading…</p> : projects.length === 0 ? (
          <p className="muted">No projects yet{canManage ? " — create one below." : ". Ask a QA lead to add you to a project."}</p>
        ) : (
          <table>
            <thead><tr><th>Project / build</th><th>Videos</th><th>Detections</th><th>Severity</th><th>Last analysis</th></tr></thead>
            <tbody>{projects.map((p) => (
              <tr key={p.id}>
                <td><strong>{p.name}</strong><div className="muted small">{p.game_build || "—"}</div>
                  {canManage && (
                    <form className="row small" style={{ marginTop: 6 }} onSubmit={(e) => {
                      e.preventDefault();
                      api.addMember(p.id, member[p.id] || "").then(() => setMember({ ...member, [p.id]: "" }))
                        .catch((x) => setErr(x.message));
                    }}>
                      <input aria-label={`Add member to ${p.name}`} placeholder="add member email" value={member[p.id] || ""}
                        onChange={(e) => setMember({ ...member, [p.id]: e.target.value })} style={{ padding: 4, border: "1px solid var(--line)", borderRadius: 6 }} />
                      <button className="btn" style={{ padding: "3px 8px" }}>Add</button>
                    </form>)}
                </td>
                <td>{p.videos}</td><td>{p.detections}</td>
                <td><div className="row">{SEVERITIES.map((s) => (p.by_severity[s] ? <span key={s} className={`sev ${s}`}>{p.by_severity[s]} {s}</span> : null))}</div></td>
                <td className="small">{fmtDate(p.last_analysis)}</td>
              </tr>))}</tbody>
          </table>
        )}
        {canManage && (
          <form className="row" style={{ marginTop: 16 }} onSubmit={(e) => {
            e.preventDefault();
            api.createProject(name, build).then(() => { setName(""); setBuild(""); load(); }).catch((x) => setErr(x.message));
          }}>
            <label className="field">New project<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
            <label className="field">Game build<input value={build} onChange={(e) => setBuild(e.target.value)} /></label>
            <button className="btn" style={{ alignSelf: "end" }}>Create project</button>
          </form>
        )}
      </section>
      <aside className="grid">
        <section className="panel">
          <h3>Severity summary</h3>
          <div className="stats">{SEVERITIES.map((s) => (
            <div className="stat" key={s}><div className="n">{totals[s]}</div><SeverityBadge s={s} /></div>))}</div>
        </section>
        <section className="panel">
          <h3>Recent activity</h3>
          {jobs.slice(0, 8).map((j) => (
            <div key={j.id} className="row" style={{ justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
              <a href={`#/job/${j.id}`}>{j.video_filename}</a><StatusText j={j} />
            </div>))}
          {jobs.length === 0 && <p className="muted small">No analyses yet.</p>}
        </section>
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------ upload & job queue (8.2)
function Upload() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [targetFps, setTargetFps] = useState(60);
  const [analysisFps, setAnalysisFps] = useState(12);
  const [dets, setDets] = useState<string[]>([...DETECTORS]);
  const [up, setUp] = useState<number | null>(null);
  const [err, setErr] = useState(""); const [ok, setOk] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { api.projects().then((p) => { setProjects(p); if (p.length) setPid((x) => x || p[0].id); }); }, []);
  useEffect(() => {
    let alive = true;
    const tick = () => api.jobs().then((j) => alive && setJobs(j)).catch(() => {});
    tick(); const t = setInterval(tick, 2000); // live queue status
    return () => { alive = false; clearInterval(t); };
  }, []);
  const pick = (f: File | undefined) => {
    setErr(""); setOk("");
    if (!f) return;
    if (!/\.(mp4|avi|mkv)$/i.test(f.name)) { setErr(`"${f.name}" is not supported. Accepted formats: .avi, .mkv, .mp4`); return; }
    setFile(f);
  };
  const submit = async () => {
    if (!file || !pid) return;
    setErr(""); setOk(""); setUp(0);
    try {
      const j = await api.upload(pid, file, { detectors: dets, analysis_fps: analysisFps, target_fps: targetFps }, setUp);
      setOk(`Queued "${j.video_filename}". You can leave this page — analysis runs in the background.`);
      setFile(null);
    } catch (x) { setErr(x instanceof ApiError ? x.message : "Upload failed"); }
    finally { setUp(null); }
  };
  return (
    <div className="grid">
      <div className="grid cols-2">
        <section className="panel grid">
          <h2>Upload gameplay video</h2>
          <label className="field">1. Project
            <select value={pid} onChange={(e) => setPid(e.target.value)}>{projects.map((p) => <option key={p.id} value={p.id}>{p.name} {p.game_build && `(${p.game_build})`}</option>)}</select>
          </label>
          <div className={`drop ${over ? "over" : ""}`} role="button" tabIndex={0} aria-label="2. Choose or drop a video file"
            onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}>
            <strong>2. {file ? file.name : "Drop a gameplay recording here or click to choose"}</strong>
            <div className="muted small">{file ? `${(file.size / 1048576).toFixed(1)} MB` : ".mp4, .mkv or .avi — up to 2 GB"}</div>
            <input ref={input} type="file" accept=".mp4,.mkv,.avi,video/mp4,video/x-matroska,video/x-msvideo" hidden onChange={(e) => pick(e.target.files?.[0])} />
          </div>
          {up !== null && <div><div className="bar" aria-label="Upload progress"><div style={{ width: `${up * 100}%` }} /></div><span className="small muted">Uploading {(up * 100).toFixed(0)}%</span></div>}
          {err && <div className="error" role="alert">{err}</div>}
          {ok && <div role="status">{ok}</div>}
          <div><button className="btn primary" disabled={!file || !pid || up !== null} onClick={submit}>3. Confirm upload</button></div>
        </section>
        <section className="panel grid">
          <h3>Analysis settings</h3>
          <label className="field">Target frame rate (FPS analyser)
            <select value={targetFps} onChange={(e) => setTargetFps(+e.target.value)}><option value={60}>60 FPS</option><option value={30}>30 FPS</option></select></label>
          <label className="field">Sampling rate for vision detectors
            <select value={analysisFps} onChange={(e) => setAnalysisFps(+e.target.value)}>{[10, 12, 15].map((v) => <option key={v} value={v}>{v} FPS</option>)}</select></label>
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="small muted">Detectors</legend>
            {DETECTORS.map((d) => (
              <label key={d} className="row small" style={{ gap: 6 }}>
                <input type="checkbox" checked={dets.includes(d)} onChange={(e) => setDets(e.target.checked ? [...dets, d] : dets.filter((x) => x !== d))} />
                {CATEGORY_LABEL[d as Category]}
              </label>))}
          </fieldset>
        </section>
      </div>
      <section className="panel">
        <h2>Job queue</h2>
        <table>
          <thead><tr><th>Video</th><th>Status</th><th>Progress</th><th>Detections</th><th>Submitted</th><th /></tr></thead>
          <tbody>{jobs.map((j) => (
            <tr key={j.id}>
              <td>{j.video_filename}</td>
              <td><StatusText j={j} />{j.error && <div className="error small">{j.error}</div>}</td>
              <td><div className="bar"><div style={{ width: `${j.progress * 100}%` }} /></div><span className="small muted">{(j.progress * 100).toFixed(0)}% {j.message}</span></td>
              <td>{j.detection_count}</td>
              <td className="small">{fmtDate(j.created_at)}</td>
              <td className="row">
                {j.status.startsWith("completed") && <a className="btn" href={`#/job/${j.id}`}>Review</a>}
                {(j.status === "failed" || j.status.startsWith("completed")) && <button className="btn" onClick={() => api.rerun(j.id).catch((x) => setErr(x.message))}>Re-run</button>}
              </td>
            </tr>))}</tbody>
        </table>
        {jobs.length === 0 && <p className="muted">No jobs yet.</p>}
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ detection review (8.3)
function useJobDetections(jobId: string, cats: string[], sevs: string[]) {
  const [job, setJob] = useState<Job | null>(null);
  const [rows, setRows] = useState<Detection[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.job(jobId).then(setJob).catch((e) => setErr(e.message)); }, [jobId]);
  useEffect(() => { setRows(null); api.detections(jobId, cats, sevs).then(setRows).catch((e) => setErr(e.message)); }, [jobId, cats.join(), sevs.join()]);
  return { job, rows, err };
}

function Filters({ cats, setCats, sevs, setSevs }: { cats: string[]; setCats: (c: string[]) => void; sevs: string[]; setSevs: (s: string[]) => void }) {
  const toggle = (list: string[], set: (x: string[]) => void, v: string) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <div className="grid" style={{ gap: 8 }}>
      <div className="row" role="group" aria-label="Filter by category">
        {CATEGORIES.map((c) => <button key={c} className="chip" aria-pressed={cats.includes(c)} onClick={() => toggle(cats, setCats, c)}>{CATEGORY_LABEL[c]}</button>)}
      </div>
      <div className="row" role="group" aria-label="Filter by severity">
        {SEVERITIES.map((s) => <button key={s} className="chip" aria-pressed={sevs.includes(s)} onClick={() => toggle(sevs, setSevs, s)}>{s.toUpperCase()}</button>)}
        {(cats.length > 0 || sevs.length > 0) && <button className="btn" onClick={() => { setCats([]); setSevs([]); }}>Clear filters</button>}
      </div>
    </div>
  );
}

function Review({ jobId }: { jobId: string }) {
  const [cats, setCats] = useState<string[]>([]);
  const [sevs, setSevs] = useState<string[]>([]);
  const { job, rows, err } = useJobDetections(jobId, cats, sevs);
  const [sel, setSel] = useState<Detection | null>(null);
  const [group, setGroup] = useState<string | null>(null); // "show all occurrences of this issue"
  const shown = useMemo(() => (rows && group ? rows.filter((r) => r.occurrence_group === group) : rows), [rows, group]);
  useEffect(() => { if (shown && (!sel || !shown.find((r) => r.id === sel.id))) setSel(shown[0] || null); }, [shown]);
  return (
    <div className="grid">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>{job ? job.video_filename : "Job"} <span className="muted small">{job && `· ${job.status.replace(/_/g, " ")} · ${job.detection_count} detections`}</span></h2>
        <a className="btn primary" href={`#/report/${jobId}`}>Report & export</a>
      </div>
      {job?.warnings?.length ? <div className="panel small"><strong>Warnings:</strong> {job.warnings.join(" · ")}</div> : null}
      <Filters cats={cats} setCats={setCats} sevs={sevs} setSevs={setSevs} />
      {group && shown && (
        <div className="panel row small" role="status">
          Showing the {shown.length} occurrences of one recurring issue.
          <button className="btn" onClick={() => setGroup(null)}>Show all detections</button>
        </div>)}
      {err && <p className="error">{err}</p>}
      <div className="grid cols-review">
        <section className="panel list-scroll" aria-label="Detections">
          {!shown ? <p className="muted">Loading…</p> : shown.length === 0 ? <p className="muted">No detections match.</p> : (
            <table>
              <thead><tr><th>Time</th><th>Category</th><th>Duration</th><th>Seen</th><th>Severity</th></tr></thead>
              <tbody>{shown.map((d) => (
                <tr key={d.id} className={`clickable ${sel?.id === d.id ? "selected" : ""}`} tabIndex={0}
                  onClick={() => setSel(d)} onKeyDown={(e) => e.key === "Enter" && setSel(d)} aria-selected={sel?.id === d.id}>
                  <td>{fmtTime(d.start_time_s)}</td>
                  <td>{CATEGORY_LABEL[d.category]}<div className="muted small">{d.subtype.replace(/_/g, " ")}</div></td>
                  <td>{(d.end_time_s - d.start_time_s).toFixed(2)} s</td>
                  <td>{recurrence(d) > 1 ? <strong title="same issue seen this many times in the video">{recurrence(d)}×</strong> : <span className="muted">once</span>}</td>
                  <td><SeverityBadge s={d.severity} /></td>
                </tr>))}</tbody>
            </table>)}
        </section>
        <section className="panel evidence grid" aria-label="Evidence">
          {!sel ? <p className="muted">Select a detection.</p> : (
            <>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h3 style={{ margin: 0 }}>{CATEGORY_LABEL[sel.category]} — {sel.subtype.replace(/_/g, " ")}</h3><SeverityBadge s={sel.severity} />
              </div>
              {sel.media.screenshot_marked ? <img src={sel.media.screenshot_marked} alt={`Screenshot at ${fmtTime(sel.peak_time_s)} with the affected area outlined`} /> : <p className="muted">No screenshot.</p>}
              {sel.media.clip ? <video key={sel.id} src={sel.media.clip} controls preload="metadata" aria-label="Evidence clip" /> : <p className="muted">No clip.</p>}
              <dl className="kv">
                <dt>Why this severity</dt><dd>{sel.severity_reason || "—"}</dd>
                <dt>What was seen</dt><dd>{sel.description}</dd>
                <dt>Time</dt><dd>{fmtTime(sel.start_time_s)} – {fmtTime(sel.end_time_s)} (peak {fmtTime(sel.peak_time_s)})</dd>
                <dt>Frames</dt><dd>{sel.start_frame} – {sel.end_frame}</dd>
                <dt>Recurrence</dt><dd>{recurrence(sel) > 1 ? (
                  <span className="row">Seen {recurrence(sel)} times in this video (this is #{String(sel.metrics.recurrence_index ?? "?")})
                    {group !== sel.occurrence_group && <button className="btn" onClick={() => setGroup(sel.occurrence_group)}>Show all {recurrence(sel)}</button>}
                  </span>) : "Seen once in this video"}</dd>
                <dt className="small">Detector</dt><dd className="small">{sel.detector} v{sel.detector_version}</dd>
                <dt className="small">Confidence</dt><dd className="small">{(sel.confidence * 100).toFixed(0)}%</dd>
              </dl>
            </>)}
        </section>
      </div>
    </div>
  );
}

const recurrence = (d: Detection) => Number(d.metrics.recurrence_count ?? 1);

// ------------------------------------------------------------------ report summary & export (8.4)
function Report({ jobId }: { jobId: string }) {
  const [cats, setCats] = useState<string[]>([]);
  const [sevs, setSevs] = useState<string[]>([]);
  const { job, rows, err } = useJobDetections(jobId, cats, sevs);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const counts = useMemo(() => {
    const m: Record<string, Record<string, number>> = {};
    CATEGORIES.forEach((c) => (m[c] = { high: 0, medium: 0, low: 0 }));
    (rows || []).forEach((d) => d.severity && m[d.category][d.severity]++);
    return m;
  }, [rows]);
  const total = (s: Severity) => (rows || []).filter((d) => d.severity === s).length;
  const max = Math.max(1, ...CATEGORIES.map((c) => SEVERITIES.reduce((a, s) => a + counts[c][s], 0)));
  const q = () => { const p = new URLSearchParams(); if (cats.length) p.set("category", cats.join(",")); if (sevs.length) p.set("severity", sevs.join(",")); return p.toString(); };
  const exp = async (kind: "json" | "pdf") => {
    setBusy(kind); setMsg("");
    try { await api.download(`/api/jobs/${jobId}/report.${kind}?${q()}`, `bug-report-${jobId}.${kind}`); setMsg(`${kind.toUpperCase()} report downloaded.`); }
    catch (x) { setMsg(x instanceof Error ? x.message : "Export failed"); }
    finally { setBusy(""); }
  };
  return (
    <div className="grid">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Bug report — {job?.video_filename}</h2>
        <div className="row">
          <a className="btn" href={`#/job/${jobId}`}>Back to review</a>
          <button className="btn" disabled={!!busy} onClick={() => exp("json")}>{busy === "json" ? "Exporting…" : "Export JSON"}</button>
          <button className="btn primary" disabled={!!busy} onClick={() => exp("pdf")}>{busy === "pdf" ? "Generating PDF…" : "Export PDF"}</button>
        </div>
      </div>
      {msg && <div role="status" className="small">{msg}</div>}
      {err && <p className="error">{err}</p>}
      <Filters cats={cats} setCats={setCats} sevs={sevs} setSevs={setSevs} />
      <section className="panel">
        <div className="stats">
          <div className="stat"><div className="n">{rows?.length ?? "…"}</div><span className="muted">Total</span></div>
          {SEVERITIES.map((s) => <div className="stat" key={s}><div className="n">{rows ? total(s) : "…"}</div><SeverityBadge s={s} /></div>)}
        </div>
      </section>
      <section className="panel">
        <h3>By category</h3>
        {CATEGORIES.map((c) => {
          const n = SEVERITIES.reduce((a, s) => a + counts[c][s], 0);
          return (
            <div className="hbar" key={c}>
              <span>{CATEGORY_LABEL[c]}</span>
              <div className="track" role="img" aria-label={`${CATEGORY_LABEL[c]}: ${SEVERITIES.map((s) => `${counts[c][s]} ${s}`).join(", ")}`}>
                {SEVERITIES.map((s) => <div key={s} className={`seg ${s}`} style={{ width: `${(counts[c][s] / max) * 100}%` }} />)}
              </div>
              <strong>{n}</strong>
            </div>);
        })}
        <div className="row small" style={{ marginTop: 8 }}>{SEVERITIES.map((s) => <SeverityBadge key={s} s={s} />)}</div>
      </section>
      <section className="panel">
        <h3>Preview</h3>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
          {(rows || []).slice(0, 12).map((d) => (
            <a key={d.id} href={`#/job/${jobId}`} className="panel" style={{ padding: 8, textDecoration: "none", color: "inherit" }}>
              {d.media.screenshot_marked && <img src={d.media.screenshot_marked} alt="" style={{ width: "100%", borderRadius: 6 }} />}
              <div className="row" style={{ justifyContent: "space-between", marginTop: 6 }}>
                <span className="small">{fmtTime(d.start_time_s)} · {d.subtype.replace(/_/g, " ")}</span><SeverityBadge s={d.severity} />
              </div>
            </a>))}
        </div>
      </section>
    </div>
  );
}
