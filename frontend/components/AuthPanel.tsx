'use client';

/** Login / registration modal with role selection and plan matrix. */
import { useEffect, useState, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { useDialog } from '@/lib/useDialog';
import {
  fetchTiers, login, register, setTier, type TierInfo, type User,
} from '@/lib/saas';

export default function AuthPanel({ onClose, onUser }: {
  onClose: () => void;
  onUser: (u: User) => void;
}) {
  const _uid = useId();
  // `tr` is the same translator under a second name: the plan-card map binds
  // its own `t`, which would otherwise shadow it inside that block.
  const { t, t: tr } = useTranslation();
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
          <h2 id="auth-title">{mode === 'login' ? t('auth.signIn') : t('auth.createWorkspace')}</h2>
          <button onClick={onClose} aria-label={mode === 'login' ? t('auth.closeSignIn') : t('auth.closeRegister')}>✕</button>
        </div>
        <div className="modal-body">
          <div className="mode-tabs">
            <button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>{t('auth.signIn')}</button>
            <button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>{t('auth.register')}</button>
          </div>
          <div className="row">
            <div>
              <label htmlFor={`${_uid}-0`}>{t('auth.email')}</label>
              <input id={`${_uid}-0`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label htmlFor={`${_uid}-1`}>{t('auth.password')}</label>
              <input id={`${_uid}-1`} type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </div>
          {mode === 'register' && (
            <>
              <div className="row">
                <div>
                  <label htmlFor={`${_uid}-2`}>{t('auth.yourName')}</label>
                  <input id={`${_uid}-2`} value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div>
                  <label htmlFor={`${_uid}-3`}>{t('auth.organization')}</label>
                  <input id={`${_uid}-3`} value={org} onChange={(e) => setOrg(e.target.value)} />
                </div>
              </div>
              <label>{t('auth.iWorkAs')}</label>
              <div className="mode-tabs">
                <button className={role === 'manager' ? 'active' : ''} onClick={() => setRole('manager')}>
                  {t('auth.roleManager')}
                </button>
                <button className={role === 'field' ? 'active' : ''} onClick={() => setRole('field')}>
                  {t('auth.roleField')}
                </button>
                <button className={role === 'presales' ? 'active' : ''} onClick={() => setRole('presales')}>
                  {t('auth.rolePresales')}
                </button>
              </div>
              <label style={{ marginTop: 8 }} id="tier-label">{t('auth.plan')}</label>
              <div style={{ display: 'flex', gap: 8 }}
                role="radiogroup" aria-labelledby="tier-label">
                {tiers.map((t) => (
                  // A plan card was a bare <div onClick>: not focusable, not
                  // announced, impossible to choose by keyboard.  It is a
                  // single-choice group, so it is a real radio.
                  <div key={t.key}
                    role="radio"
                    tabIndex={pickedTier === t.key ? 0 : -1}
                    aria-checked={pickedTier === t.key}
                    aria-label={t.label}
                    className="panel"
                    style={{ flex: 1, cursor: 'pointer',
                             borderColor: pickedTier === t.key ? 'var(--accent)' : undefined }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault(); setPickedTier(t.key);
                      }
                    }}
                    onClick={() => setPickedTier(t.key)}>
                    <b>{t.label}</b>
                    <div style={{ fontSize: 12, color: 'var(--ink-secondary)' }}>
                      {t.price_month_usd === 0 ? tr('auth.free') : tr('auth.perMonth', { price: t.price_month_usd })}
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
          {error && <div className="error-box" role="alert">{error}</div>}
        </div>
        <div className="modal-foot">
          <span className="hint">{t('auth.selfHostedNote')}</span>
          <button className="primary" disabled={busy || !email || password.length < 8}
            onClick={submit}>
            {busy ? t('auth.working') : mode === 'login' ? t('auth.signIn') : t('auth.createAccount')}
          </button>
        </div>
      </div>
    </div>
  );
}
