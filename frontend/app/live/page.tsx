'use client';

/** Live Operations digital-twin dashboard — client-only (Leaflet + SSE). */
import dynamic from 'next/dynamic';
import Link from 'next/link';
import 'leaflet/dist/leaflet.css';

const LiveOps = dynamic(() => import('@/components/LiveOps'), { ssr: false });

export default function LivePage() {
  return (
    <div className="live-page">
      <div className="live-topbar">
        <Link href="/">← AntennaMaster</Link>
        <span>Live Operations</span>
      </div>
      <LiveOps />
    </div>
  );
}
