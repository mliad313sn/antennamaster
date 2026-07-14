/** SaaS API client: auth, projects, tiers, costs, jobs, PDF reports. */

export interface User {
  id: number;
  email: string;
  name: string;
  role: 'manager' | 'field' | 'presales';
  tier: 'basic' | 'pro' | 'enterprise';
  org_name: string;
  has_logo: boolean;
}

export interface Project {
  id: number;
  name: string;
  kind: string;
  data: Record<string, unknown>;
  share_token: string | null;
  created_at: number;
  updated_at: number;
}

export interface TierInfo {
  key: string;
  label: string;
  price_month_usd: number;
  highlights: string[];
}

export interface CostEstimate {
  technology: string;
  sites: number;
  bom_per_site: { item: string; qty: number; unit_usd: number; line_usd: number }[];
  capex_per_site_usd: number;
  opex_per_site_year_usd: number;
  capex_total_usd: number;
  opex_total_year_usd: number;
  tco_5y_usd: number;
}

export interface Job {
  id: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
}

const TOKEN_KEY = 'am_token';

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string | null): void {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* unavailable */ }
}

export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep */ }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

// ------------------------------------------------------------------- auth
export async function register(email: string, password: string, name: string,
  role: string, orgName: string): Promise<User> {
  const body = await call<{ token: string; user: User }>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, name, role, org_name: orgName }),
  });
  setToken(body.token);
  return body.user;
}

export async function login(email: string, password: string): Promise<User> {
  const body = await call<{ token: string; user: User }>('/api/auth/login', {
    method: 'POST', body: JSON.stringify({ email, password }),
  });
  setToken(body.token);
  return body.user;
}

export async function fetchMe(): Promise<User | null> {
  if (!getToken()) return null;
  try {
    return (await call<{ user: User }>('/api/auth/me')).user;
  } catch { setToken(null); return null; }
}

export async function fetchTiers(): Promise<TierInfo[]> {
  return (await call<{ tiers: TierInfo[] }>('/api/auth/tiers')).tiers;
}

export async function setTier(tier: string): Promise<User> {
  return (await call<{ user: User }>('/api/auth/tier', {
    method: 'POST', body: JSON.stringify({ tier }) })).user;
}

export async function fetchAudit(): Promise<{ action: string; detail: string;
  email: string | null; ts: number }[]> {
  return (await call<{ entries: never[] }>('/api/auth/audit')).entries;
}

export async function uploadLogo(file: File): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch('/api/auth/logo', {
    method: 'POST', body: form, headers: authHeaders() });
  if (!resp.ok) throw new Error((await resp.json()).detail ?? resp.statusText);
}

// --------------------------------------------------------------- projects
export async function listProjects(): Promise<Project[]> {
  return (await call<{ projects: Project[] }>('/api/projects')).projects;
}
export async function createProject(name: string, data: Record<string, unknown>,
  kind = 'coverage'): Promise<Project> {
  return (await call<{ project: Project }>('/api/projects', {
    method: 'POST', body: JSON.stringify({ name, kind, data }) })).project;
}
export async function updateProject(id: number, data: Record<string, unknown>): Promise<void> {
  await call(`/api/projects/${id}`, { method: 'PUT', body: JSON.stringify({ data }) });
}
export async function duplicateProject(id: number): Promise<Project> {
  return (await call<{ project: Project }>(`/api/projects/${id}/duplicate`,
    { method: 'POST' })).project;
}
export async function shareProject(id: number): Promise<string> {
  return (await call<{ share_token: string }>(`/api/projects/${id}/share`,
    { method: 'POST' })).share_token;
}
export async function deleteProject(id: number): Promise<void> {
  await call(`/api/projects/${id}`, { method: 'DELETE' });
}

// ------------------------------------------------------------ costs & jobs
export async function fetchCosts(technology: string, sites: number): Promise<CostEstimate> {
  return call(`/api/saas/costs?technology=${encodeURIComponent(technology)}&sites=${sites}`);
}

export async function startAsyncCoverage(body: Record<string, unknown>): Promise<string> {
  return (await call<{ job_id: string }>('/api/saas/coverage/async', {
    method: 'POST', body: JSON.stringify(body) })).job_id;
}

export async function fetchJob(jobId: string): Promise<Job> {
  return call(`/api/saas/jobs/${jobId}`);
}

/** Poll a job until terminal, reporting progress via callback. */
export async function awaitJob(jobId: string,
  onProgress: (p: number) => void): Promise<Job> {
  for (;;) {
    const job = await fetchJob(jobId);
    onProgress(job.progress);
    if (job.status === 'done' || job.status === 'failed') return job;
    await new Promise((r) => setTimeout(r, 400));
  }
}

// ---------------------------------------------------------------- reports
export async function downloadReportPdf(body: Record<string, unknown>): Promise<void> {
  const resp = await fetch('/api/saas/report.pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail ?? resp.statusText);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'rf-study.pdf';
  a.click();
  URL.revokeObjectURL(url);
}
