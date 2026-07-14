'use client';

/** Shared top navigation for the role dashboards. */
import Link from 'next/link';

export default function DashNav({ active }: { active: string }) {
  return (
    <header className="app-header">
      <h1>AntennaMaster</h1>
      <nav style={{ display: 'flex', gap: 10 }}>
        <Link href="/" className={`nav-link ${active === 'planner' ? 'on' : ''}`}>Planner</Link>
        <Link href="/dashboard" className={`nav-link ${active === 'dashboard' ? 'on' : ''}`}>Command Center</Link>
        <Link href="/field" className={`nav-link ${active === 'field' ? 'on' : ''}`}>Tactical</Link>
        <Link href="/pitch" className={`nav-link ${active === 'pitch' ? 'on' : ''}`}>Pitch</Link>
      </nav>
    </header>
  );
}
