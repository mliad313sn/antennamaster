'use client';

/**
 * Account & privacy: the two rights a signed-in user has over their own data.
 *
 * Both were previously operator-only: exporting meant asking someone to run a
 * query, and closing an account meant asking someone to run DELETE. A product
 * a European customer's DPO has to sign off on cannot make its users file a
 * ticket to exercise art. 15 and art. 17, so they are self-serve here.
 *
 * Erasure is irreversible and reaches every artefact the account owns, so it
 * is deliberately awkward: a second screen, the password again, and the word
 * DELETE typed out. That friction is the feature.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDialog } from '@/lib/useDialog';
import { eraseAccount, exportAccount, type EraseReceipt, type User } from '@/lib/saas';

export default function AccountPanel({ user, onClose, onErased }: {
  user: User;
  onClose: () => void;
  onErased: () => void;
}) {
  const { t } = useTranslation();
  const dialogRef = useDialog(onClose);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [danger, setDanger] = useState(false);
  const [password, setPassword] = useState('');
  const [typed, setTyped] = useState('');
  const [receipt, setReceipt] = useState<EraseReceipt | null>(null);

  async function download() {
    setBusy(true); setError(null); setStatus(null);
    try {
      const dump = await exportAccount();
      // Build the file in the page: the export needs the Authorization
      // header, so a plain <a href> to the endpoint would download a 401.
      const url = URL.createObjectURL(new Blob([JSON.stringify(dump, null, 2)],
        { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `antennamaster-account-${user.id}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setStatus(t('account.exportDone'));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function erase() {
    setBusy(true); setError(null);
    try {
      setReceipt(await eraseAccount(password));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 560 }} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="account-title"
        ref={dialogRef} tabIndex={-1}>
        <div className="modal-head">
          <h2 id="account-title">{t('account.title')}</h2>
          <button onClick={onClose} aria-label={t('account.close')}>✕</button>
        </div>

        <div className="modal-body">
          {receipt ? (
            <div role="status">
              <p>{t('account.erasedDone')}</p>
              <ul style={{ fontSize: 12, color: 'var(--ink-secondary)' }}>
                <li>{t('account.erasedProjects', { n: receipt.projects })}</li>
                <li>{t('account.erasedDxf', { n: receipt.dxf })}</li>
                <li>{t('account.erasedAntennas', { n: receipt.antennas })}</li>
                <li>{t('account.erasedResults', { n: receipt.results })}</li>
                <li>{t('account.erasedAudit', { n: receipt.audit_pseudonymised })}</li>
              </ul>
              <button className="primary" onClick={onErased}>{t('account.done')}</button>
            </div>
          ) : (
            <>
              <p className="hint">{user.email}{user.org_name ? ` · ${user.org_name}` : ''}</p>

              <h3>{t('account.exportTitle')}</h3>
              <p className="hint">{t('account.exportHelp')}</p>
              <button disabled={busy} onClick={download}>{t('account.exportBtn')}</button>

              <h3 style={{ marginTop: 20 }}>{t('account.deleteTitle')}</h3>
              <p className="hint">{t('account.deleteHelp')}</p>
              {!danger ? (
                <button onClick={() => setDanger(true)}>{t('account.deleteBtn')}</button>
              ) : (
                <div className="warning-box">
                  <p>{t('account.deleteConfirmHelp')}</p>
                  <label htmlFor="erase-pw">{t('account.password')}</label>
                  <input id="erase-pw" type="password" value={password}
                    onChange={(e) => setPassword(e.target.value)} />
                  <label htmlFor="erase-word">{t('account.typeDelete')}</label>
                  <input id="erase-word" value={typed}
                    onChange={(e) => setTyped(e.target.value)} />
                  <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <button onClick={() => { setDanger(false); setTyped(''); setPassword(''); }}>
                      {t('account.cancel')}
                    </button>
                    <button className="danger" disabled={busy || !password || typed !== 'DELETE'}
                      onClick={erase}>
                      {busy ? t('auth.working') : t('account.deleteForever')}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
          {status && <div className="ok-box" role="status">{status}</div>}
          {error && <div className="error-box" role="alert">{error}</div>}
        </div>
      </div>
    </div>
  );
}
