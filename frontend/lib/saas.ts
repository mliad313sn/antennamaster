/** SaaS API client: auth, projects, tiers, costs, jobs, PDF reports. */
import { TOKEN_KEY, authHeaders, getToken } from './token';
import { apiFetch, HEAVY_TIMEOUT_MS } from './api';

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
  /** Epoch seconds, or null for a link the owner chose never to expire. */
  share_expires_at: number | null;
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
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
}

// Re-exported so the many existing `from '@/lib/saas'` imports keep working;
// they live in token.ts now so api.ts can read them without a cycle.
export { authHeaders, getToken };

export function setToken(t: string | null): void {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* unavailable */ }
  // Dropping the token is not enough on a shared field tablet: the service
  // worker's offline cache still holds this account's studies and projects,
  // and the next person to lose signal would be handed them. Tell it to
  // purge. Best-effort — no SW, no problem, there is then nothing cached.
  if (!t) {
    try { navigator.serviceWorker?.controller?.postMessage({ type: 'am-signout' }); }
    catch { /* not registered */ }
  }
}


async function call<T>(url: string, init?: RequestInit): Promise<T> {
  // Through apiFetch, so an account call cannot hang forever on a dropped
  // connection: a bare fetch never settles, and the sign-in dialog would sit
  // on "Working…" with no error and no way back except a reload.
  const resp = await apiFetch(url, {
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

export interface AuditEntry {
  action: string;
  detail: string;
  email: string | null;
  ts: number;
}

export async function fetchAudit(): Promise<AuditEntry[]> {
  return (await call<{ entries: AuditEntry[] }>('/api/auth/audit')).entries;
}

/** Right of access / portability (GDPR art. 15 & 20). Returns the whole
 *  account dump so the caller can offer it as a download. */
export async function exportAccount(): Promise<Record<string, unknown>> {
  return call<Record<string, unknown>>('/api/auth/export');
}

export interface EraseReceipt {
  projects: number; dxf: number; antennas: number; results: number;
  logo: boolean; audit_pseudonymised: number; subject: string | null;
}

/** Right to erasure (GDPR art. 17). Irreversible: the caller must have
 *  collected the password and an explicit confirmation first. */
export async function eraseAccount(password: string): Promise<EraseReceipt> {
  const body = await call<{ erased: EraseReceipt }>('/api/auth/account', {
    method: 'DELETE',
    body: JSON.stringify({ password, confirm: 'DELETE' }),
  });
  setToken(null);
  return body.erased;
}

export async function uploadLogo(file: File): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  const resp = await apiFetch('/api/auth/logo', {
    method: 'POST', body: form, headers: authHeaders() }, HEAVY_TIMEOUT_MS);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(detail);
  }
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
export interface ShareLink { share_token: string; expires_at: number | null; }

/** Mint a share link. Calling it again rotates the token, which is how an
 *  owner cuts off a link that has already been forwarded too far.
 *  `expiresDays: null` opts out of expiry explicitly. */
export async function shareProject(id: number, expiresDays: number | null = 30):
Promise<ShareLink> {
  return call<ShareLink>(`/api/projects/${id}/share`, {
    method: 'POST', body: JSON.stringify({ expires_days: expiresDays }) });
}

/** Revoke the link: a forwarded copy stops working immediately. */
export async function unshareProject(id: number): Promise<void> {
  await call(`/api/projects/${id}/share`, { method: 'DELETE' });
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

/** Ask the server to stop a running simulation. */
export async function cancelJob(jobId: string): Promise<void> {
  await call(`/api/saas/jobs/${jobId}`, { method: 'DELETE' });
}

/** Poll a job until terminal, reporting progress via callback. */
export async function awaitJob(jobId: string,
  onProgress: (p: number) => void): Promise<Job> {
  for (;;) {
    const job = await fetchJob(jobId);
    onProgress(job.progress);
    if (job.status === 'done' || job.status === 'failed'
        || job.status === 'cancelled') return job;
    await new Promise((r) => setTimeout(r, 400));
  }
}

// ---------------------------------------------------------------- reports
export async function downloadReportPdf(body: Record<string, unknown>): Promise<void> {
  const resp = await apiFetch('/api/saas/report.pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  }, HEAVY_TIMEOUT_MS);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail ?? detail; } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'rf-study.pdf';
  a.click();
  URL.revokeObjectURL(url);
}
