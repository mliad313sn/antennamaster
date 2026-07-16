'use client';

import { useTranslation } from 'react-i18next';

/** First tab stop on every page: lets keyboard and screen-reader users jump
 *  past the header chrome straight to the main content region. */
export default function SkipLink() {
  const { t } = useTranslation();
  return <a href="#main" className="skip-link">{t('a11y.skipToMain')}</a>;
}
