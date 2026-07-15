// Copy CesiumJS' prebuilt static assets into public/cesium so the 3D globe
// loads them at runtime via CESIUM_BASE_URL. We load Cesium as a runtime
// <script> (its IIFE global build) rather than bundling it through webpack,
// which keeps the Next build fast and avoids Cesium's AMD/worker quirks.
import { cp, mkdir, access } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const src = `${root}/node_modules/cesium/Build/Cesium`;
const dest = `${root}/public/cesium`;

try {
  await access(src);
} catch {
  console.warn('[copy-cesium] cesium not installed — skipping (3D view will be unavailable)');
  process.exit(0);
}

await mkdir(dest, { recursive: true });
for (const part of ['Workers', 'Assets', 'ThirdParty', 'Widgets', 'Cesium.js']) {
  await cp(`${src}/${part}`, `${dest}/${part}`, { recursive: true }).catch((e) => {
    console.warn(`[copy-cesium] could not copy ${part}: ${e.message}`);
  });
}
console.log('[copy-cesium] Cesium assets staged at public/cesium');
