// Thin client for the FastAPI backend. The session token is kept in sessionStorage
// (cleared when the tab closes); evidence files use short-lived signed URLs from the API.

export type Role = "tester" | "developer" | "qa_lead" | "admin";
export type Severity = "high" | "medium" | "low";
export type Category = "npc_anomaly" | "texture_pop_in" | "fps_drop" | "animation_glitch" | "collision_clipping";

export interface User { id: string; email: string; full_name: string; role: Role; is_active: boolean }
export interface Project {
  id: string; name: string; game_build: string; videos: number; jobs: number; detections: number;
  by_severity: Record<string, number>; last_analysis: string | null;
}
export interface Job {
  id: string; project_id: string; video_filename: string; video_duration_s: number | null; status: string;
  progress: number; message: string; options: Record<string, unknown>; created_at: string;
  finished_at: string | null; error: string | null; warnings: string[]; detection_count: number;
}
export interface BBox { x: number; y: number; w: number; h: number }
export interface Detection {
  id: string; category: Category; subtype: string; detector: string; detector_version: string;
  start_time_s: number; end_time_s: number; peak_time_s: number; start_frame: number; end_frame: number;
  peak_frame: number; confidence: number; bbox: BBox | null; description: string;
  severity: Severity | null; severity_reason: string | null; metrics: Record<string, unknown>;
  occurrence_group: string | null; // same defect recurring (same subtype, same screen area)
  media: { screenshot: string | null; screenshot_marked: string | null; clip: string | null };
}

export const CATEGORY_LABEL: Record<Category, string> = {
  npc_anomaly: "NPC anomaly", texture_pop_in: "Texture pop-in", fps_drop: "FPS drop / freeze",
  animation_glitch: "Animation glitch", collision_clipping: "Collision / clipping",
};
export const CATEGORIES = Object.keys(CATEGORY_LABEL) as Category[];
export const SEVERITIES: Severity[] = ["high", "medium", "low"];
export const DETECTORS = ["fps_drop", "texture_pop_in", "animation_glitch", "npc_anomaly", "collision_clipping"];

const KEY = "gameqa.token";
let token: string | null = (() => { try { return sessionStorage.getItem(KEY); } catch { return null; } })();
export function setToken(t: string | null) {
  token = t;
  try { t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY); } catch { /* private mode */ }
}
export const hasToken = () => !!token;

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const r = await fetch(path, { ...init, headers });
  if (r.status === 401) { setToken(null); window.dispatchEvent(new Event("gameqa:logout")); }
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* */ }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    req<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => req<User>("/api/auth/me"),
  projects: () => req<Project[]>("/api/projects"),
  createProject: (name: string, game_build: string) =>
    req<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name, game_build }) }),
  addMember: (pid: string, email: string) =>
    req(`/api/projects/${pid}/members`, { method: "POST", body: JSON.stringify({ email }) }),
  jobs: (project_id?: string) => req<Job[]>(`/api/jobs${project_id ? `?project_id=${project_id}` : ""}`),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  rerun: (id: string) => req<Job>(`/api/jobs/${id}/rerun`, { method: "POST" }),
  deleteJob: (id: string) => req(`/api/jobs/${id}`, { method: "DELETE" }),
  detections: (id: string, cats: string[], sevs: string[]) => {
    const q = new URLSearchParams();
    if (cats.length) q.set("category", cats.join(","));
    if (sevs.length) q.set("severity", sevs.join(","));
    return req<Detection[]>(`/api/jobs/${id}/detections?${q}`);
  },
  upload: (pid: string, file: File, opts: { detectors: string[]; analysis_fps: number; target_fps: number },
           onProgress: (f: number) => void) =>
    new Promise<Job>((resolve, reject) => {
      // XMLHttpRequest (not fetch) for upload progress events on multi-GB files
      const fd = new FormData();
      fd.append("file", file);
      fd.append("detectors", opts.detectors.join(","));
      fd.append("analysis_fps", String(opts.analysis_fps));
      fd.append("target_fps", String(opts.target_fps));
      const x = new XMLHttpRequest();
      x.open("POST", `/api/projects/${pid}/videos`);
      if (token) x.setRequestHeader("Authorization", `Bearer ${token}`);
      x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      x.onload = () => {
        let body: any = {};
        try { body = JSON.parse(x.responseText); } catch { /* */ }
        x.status < 300 ? resolve(body) : reject(new ApiError(x.status, body.detail || x.statusText));
      };
      x.onerror = () => reject(new ApiError(0, "network error"));
      x.send(fd);
    }),
  download: async (path: string, filename: string) => {
    const r = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!r.ok) throw new ApiError(r.status, r.statusText);
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  },
};

export const fmtTime = (s: number) => {
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${(s - m * 60).toFixed(2).padStart(5, "0")}`;
};
export const fmtDate = (d: string | null) => (d ? new Date(d).toLocaleString() : "—");
