'use client';

import { useEffect, useState } from 'react';
import { I18nextProvider } from 'react-i18next';
import i18n, { storedLocale, LOCALE_KEY } from '@/lib/i18n';

/**
 * Applies the persisted locale on mount and keeps <html lang> + localStorage
 * in sync with every language change.  Children render immediately (English
 * first paint); when the stored locale differs, the switch happens on mount —
 * the same "hydrate then restore" pattern the session uses elsewhere.
 */
export default function I18nProvider({ children }: { children: React.ReactNode }) {
  const [, force] = useState(0);

  useEffect(() => {
    const target = storedLocale();
    const onLang = (lng: string) => {
      document.documentElement.lang = lng;
      try { localStorage.setItem(LOCALE_KEY, lng); } catch { /* ignore */ }
    };
    i18n.on('languageChanged', onLang);
    if (target !== i18n.language) {
      i18n.changeLanguage(target).then(() => force((n) => n + 1));
    } else {
      onLang(i18n.language);
    }
    return () => { i18n.off('languageChanged', onLang); };
  }, []);

  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
