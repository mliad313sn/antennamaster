'use client';

/**
 * Client-side i18next instance (the app is entirely client components, so a
 * headless SSR i18n framework isn't needed).  Resources are bundled so there
 * is no async load flash; the stored locale is applied on mount by
 * I18nProvider.  English is the base/fallback.
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from '@/locales/en/common.json';
import fr from '@/locales/fr/common.json';

export const LOCALES = ['en', 'fr'] as const;
export type Locale = (typeof LOCALES)[number];
export const LOCALE_KEY = 'am_locale';

export function storedLocale(): Locale {
  if (typeof window === 'undefined') return 'en';
  const v = window.localStorage.getItem(LOCALE_KEY);
  return v === 'fr' || v === 'en' ? v : 'en';
}

if (!i18n.isInitialized) {
  i18n.use(initReactI18next).init({
    resources: { en: { common: en }, fr: { common: fr } },
    lng: 'en',                       // server + first client paint; synced on mount
    fallbackLng: 'en',
    defaultNS: 'common',
    ns: ['common'],
    interpolation: { escapeValue: false },
    returnNull: false,
    react: { useSuspense: false },
  });
}

export default i18n;
