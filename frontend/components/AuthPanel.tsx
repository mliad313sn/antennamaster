'use client';

/** Login / registration modal with role selection and plan matrix. */
import { useEffect, useState, useId } from 'react';
import { useDialog } from '@/lib/useDialog';
import {
  fetchTiers, login, register, setTier, type TierInfo, type User,
} from '@/lib/saas';

export default function AuthPanel({ onClose, onUser }: {
  onClose: () => void;
  onUser: (u: User) => void;
}) {
  const _uid = useId();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [org, setOrg] = useState('');
  const [role, setRole] = useState('field');
  const [tiers, setTiers] = useState<TierInfo[]>([]);
  const [pickedTier, setPickedTier] = useState('basic');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchTiers().then(setTiers).catch(() => {}); }, []);
  const dialogRef = useDialog(onClose);

  async function submit() {
    setBusy(true); setError(null);
    try {
      let user = mode === 'login'
        ? await login(email, password)
        : await register(email, password, name, role, org);
      if (mode === 'register' && pickedTier !== 'basic') {
        user = await setTier(pickedTier);
      }
      onUser(user);
      onClose();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 620 }} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="auth-title"
        ref={dialogRef} tabIndex={-1}>
        <div className="modal-head">
          <h2 id="auth-title">{mode === 'login' ? 'Sign in' : 'Create your workspace'}</h2>
          <button onClick={onClose} aria-label={mode === 'login' ? 'Close sign-in dialog' : 'Close registration dialog'}>✕</button>
        </div>
        <div className="modal-body">
          <div className="mode-tabs">
            <button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>Sign in</button>
            <button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Register</button>
          </div>
          <div className="row">
            <div>
              <label htmlFor={`${_uid}-0`}>Email</label>
              <input id={`${_uid}-0`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label htmlFor={`${_uid}-1`}>Password (min 8 chars)</label>
              <input id={`${_uid}-1`} type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </div>
          {mode === 'register' && (
            <>
              <div className="row">
                <div>
                  <label htmlFor={`${_uid}-2`}>Your name</label>
                  <input id={`${_uid}-2`} value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div>
                  <label htmlFor={`${_uid}-3`}>Organization</label>
                  <input id={`${_uid}-3`} value={org} onChange={(e) => setOrg(e.target.value)} />
                </div>
              </div>
              <label>I work as…</label>
              <div className="mode-tabs">
                <button className={role === 'manager' ? 'active' : ''} onClick={() => setRole('manager')}>
                  IT / OT Manager
                </button>
                <button className={role === 'field' ? 'active' : ''} onClick={() => setRole('field')}>
                  Field Tech / RF Engineer
                </button>
                <button className={role === 'presales' ? 'active' : ''} onClick={() => setRole('presales')}>
                  Pre-Sales Architect
                </button>
              </div>
              <label style={{ marginTop: 8 }}>Plan</label>
              <div style={{ display: 'flex', gap: 8 }}>
                {tiers.map((t) => (
                  <div key={t.key}
                    className="panel"
                    style={{ flex: 1, cursor: 'pointer',
                             borderColor: pickedTier === t.key ? 'var(--accent)' : undefined }}
                    onClick={() => setPickedTier(t.key)}>
                    <b>{t.label}</b>
                    <div style={{ fontSize: 12, color: 'var(--ink-secondary)' }}>
                      {t.price_month_usd === 0 ? 'Free' : `$${t.price_month_usd}/mo`}
                    </div>
                    <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 11,
                                 color: 'var(--ink-secondary)' }}>
                      {t.highlights.map((h) => <li key={h}>{h}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
            </>
          )}
          {error && <div className="error-box">{error}</div>}
        </div>
        <div className="modal-foot">
          <span className="hint">Open self-hosted mode keeps all features free without an account.</span>
          <button className="primary" disabled={busy || !email || password.length < 8}
            onClick={submit}>
            {busy ? 'Working…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </div>
      </div>
    </div>
  );
}
