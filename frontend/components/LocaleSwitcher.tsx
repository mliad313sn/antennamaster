'use client';

import { useTranslation } from 'react-i18next';
import { LOCALES, type Locale } from '@/lib/i18n';

/**
 * Persistent language switcher for the header.  Compact segmented control —
 * two locales today (EN / FR), extendable by adding to LOCALES + a
 * locales/<lng>/common.json.
 */
export default function LocaleSwitcher() {
  const { i18n, t } = useTranslation();
  const current = (LOCALES as readonly string[]).includes(i18n.language)
    ? (i18n.language as Locale) : 'en';
  return (
    <div className="locale-switch" role="group" aria-label={t('locale.label')}>
      {LOCALES.map((lng) => (
        <button
          key={lng}
          type="button"
          className={current === lng ? 'active' : ''}
          aria-pressed={current === lng}
          onClick={() => i18n.changeLanguage(lng)}
          title={t(`locale.${lng}`)}
        >
          {lng.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
