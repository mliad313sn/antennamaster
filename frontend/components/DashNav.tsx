'use client';

/** Shared top navigation for the role dashboards. */
import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import LocaleSwitcher from '@/components/LocaleSwitcher';

export default function DashNav({ active }: { active: string }) {
  const { t } = useTranslation();
  return (
    <header className="app-header">
      <h1>{t('app.title')}</h1>
      <nav style={{ display: 'flex', gap: 10 }}>
        <Link href="/" className={`nav-link ${active === 'planner' ? 'on' : ''}`}>{t('nav.planner')}</Link>
        <Link href="/dashboard" className={`nav-link ${active === 'dashboard' ? 'on' : ''}`}>{t('nav.dashboard')}</Link>
        <Link href="/field" className={`nav-link ${active === 'field' ? 'on' : ''}`}>{t('nav.field')}</Link>
        <Link href="/pitch" className={`nav-link ${active === 'pitch' ? 'on' : ''}`}>{t('nav.pitch')}</Link>
        <Link href="/live" className={`nav-link ${active === 'live' ? 'on' : ''}`}>{t('nav.live')}</Link>
      </nav>
      <div style={{ marginLeft: 'auto' }}><LocaleSwitcher /></div>
    </header>
  );
}
