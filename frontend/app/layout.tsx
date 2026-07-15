import type { Metadata, Viewport } from 'next';
import 'leaflet/dist/leaflet.css';
import './globals.css';
import ServiceWorker from '@/components/ServiceWorker';
import I18nProvider from '@/components/I18nProvider';

export const metadata: Metadata = {
  title: 'AntennaMaster — RF Coverage Simulator',
  description:
    'RF coverage simulator: SRTM + DXF terrain fusion, propagation studies, '
    + 'coverage maps, indoor & underground — usable in the field.',
  manifest: '/manifest.webmanifest',
  appleWebApp: { capable: true, title: 'AntennaMaster', statusBarStyle: 'black-translucent' },
  icons: { icon: '/icon.svg', apple: '/icon.svg' },
};

export const viewport: Viewport = {
  themeColor: '#2a78d6',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <I18nProvider>
          {children}
          <ServiceWorker />
        </I18nProvider>
      </body>
    </html>
  );
}
