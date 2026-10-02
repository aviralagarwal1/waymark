// Renders the link-preview card and the app icons from brand.json and the trail-W mark, by screenshotting HTML in headless Chrome. The PNGs are checked
// in rather than built, because the Docker build has no browser; rerun this
// (`npm run identity`) whenever the name, tagline, description, or mark changes.
// Set CHROME to the browser's path if it is not in the usual place.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const web = join(here, '..')
const brand = JSON.parse(readFileSync(join(web, '../waymark/brand.json'), 'utf8'))
const font = pathToFileURL(join(web, 'node_modules/@fontsource-variable/instrument-sans/files/instrument-sans-latin-wght-normal.woff2')).href

const chrome = process.env.CHROME || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].find(existsSync)
if (!chrome) throw new Error('No Chrome found; set CHROME to its path.')

const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;')

// The same W as `Mark` in components.tsx and the favicon.
const TRAIL_W = 'M3 6C6 14 8.5 22 12 22S16.5 11 20 11 24.5 22 28 22 34 14 37 6'
const mark = size => `<svg width="${size}" height="${size * 0.7}" viewBox="0 0 40 28" overflow="visible">
  <path d="${TRAIL_W}" fill="none" stroke="#ece9e2" stroke-opacity="0.25" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="${TRAIL_W}" fill="none" stroke="#ece9e2" stroke-width="2.4" stroke-linecap="round" stroke-dasharray="0.1 4.4"/>
  <circle cx="37" cy="6" r="3.5" fill="#f2b544"/></svg>`

// Contours as on the landing page (contourPaths in Landing.tsx).
function contours(cx, cy, rings, step, seed) {
  return Array.from({length: rings}, (_, k) => {
    const R = (k + 1) * step
    let d = ''
    for (let i = 0; i <= 96; i++) {
      const t = i / 96 * Math.PI * 2
      const r = R * (1 + 0.12 * Math.sin(3 * t + seed + k * 0.15) + 0.07 * Math.sin(5 * t + seed * 2 - k * 0.1))
      d += `${i ? 'L' : 'M'}${(cx + r * Math.cos(t) * 1.35).toFixed(1)} ${(cy + r * Math.sin(t)).toFixed(1)}`
    }
    return `<path d="${d}Z" stroke="${(k + 1) % 5 === 0 ? '#1d2935' : '#16202b'}" stroke-width="${(k + 1) % 5 === 0 ? 1.5 : 1}"/>`
  }).join('')
}

const page = (width, height, body) => `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: 'Instrument Sans'; src: url('${font}') format('woff2'); font-weight: 400 700; }
* { margin: 0; box-sizing: border-box; }
html, body { width: ${width}px; height: ${height}px; overflow: hidden; background: #0b1016; }
body { font-family: 'Instrument Sans', sans-serif; color: #ece9e2; }
</style></head><body>${body}</body></html>`

// The card: the wordmark, the tagline and description from brand.json, and the
// hero's trail climbing to the one lit waypoint. No address, because every
// self-hosted install serves the same image.
function card(width, height) {
  const pad = 80
  // Broken where the landing hero breaks it (splitAfter in Landing.tsx); if
  // the copy changes and the marker is gone, the text wraps instead.
  const at = brand.tagline.indexOf('job ')
  const tagline = at < 0 ? escape(brand.tagline) : `${escape(brand.tagline.slice(0, at + 4))}<br>${escape(brand.tagline.slice(at + 4))}`
  const x = i => width * (0.66 + i * 0.065)
  const y = i => height * (0.78 - i * 0.14)
  const points = [0, 1, 2, 3, 4].map(i => [x(i), y(i)])
  const route = `M${points[0]} ` + points.slice(1).map(([px, py], i) => {
    const [ax, ay] = points[i]
    return `C${ax + (px - ax) * 0.55} ${ay} ${px - (px - ax) * 0.55} ${py} ${px} ${py}`
  }).join(' ')
  const waypoints = points.slice(0, -1).map(([px, py]) => `<circle cx="${px}" cy="${py}" r="9" fill="#0b1016" stroke="#b9c0c7" stroke-width="3"/>`).join('')
  const [ox, oy] = points.at(-1)
  return page(width, height, `
<div style="position:absolute;inset:0;background:radial-gradient(120% 70% at 75% 0%, #16202c 0%, #0b1016 60%)"></div>
<svg width="${width}" height="${height}" style="position:absolute;inset:0" fill="none">
  <defs><linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0.45" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <mask id="m"><rect width="${width}" height="${height}" fill="url(#fade)"/></mask></defs>
  <g mask="url(#m)">${contours(width * 0.86, height * 0.18, 22, 26, 0.6)}</g>
  <path d="${route}" stroke="#f2b544" stroke-width="12" stroke-opacity="0.12" stroke-linecap="round"/>
  <path d="${route}" stroke="#f2b544" stroke-width="3" stroke-linecap="round" stroke-dasharray="0.1 12"/>
  ${waypoints}
  <circle cx="${ox}" cy="${oy}" r="34" fill="#f2b544" fill-opacity="0.12"/>
  <circle cx="${ox}" cy="${oy}" r="22" fill="#f2b544" fill-opacity="0.2"/>
  <circle cx="${ox}" cy="${oy}" r="11" fill="#f2b544"/>
</svg>
<div style="position:absolute;left:${pad}px;top:${pad - 6}px;display:flex;align-items:center;gap:16px;font-size:38px;font-weight:500">${mark(62)}${escape(brand.name)}</div>
<div style="position:absolute;left:${pad}px;bottom:${pad}px;width:${width * 0.6}px">
  <div style="font-size:100px;line-height:1.02;letter-spacing:-0.035em;font-weight:400">${tagline}</div>
  <div style="margin-top:30px;font-size:29px;line-height:1.45;color:#8b98a5;max-width:30ch">${escape(brand.description)}</div>
</div>`)
}

// Icons are full bleed: iOS and Android round or mask the corners themselves,
// so the mark sits inside the central safe zone of a maskable icon.
function icon(size) {
  const w = size * 0.62
  return page(size, size, `<div style="width:${size}px;height:${size}px;display:grid;place-items:center;background:#0b1016">${mark(w)}</div>`)
}

const outputs = [
  ['public/og.png', 1200, 630, card(1200, 630)],
  ['public/apple-touch-icon.png', 180, 180, icon(180)],
  ['public/icon-192.png', 192, 192, icon(192)],
  ['public/icon-512.png', 512, 512, icon(512)],
]

const scratch = mkdtempSync(join(tmpdir(), 'waymark-identity-'))
try {
  for (const [out, width, height, html] of outputs) {
    const source = join(scratch, 'page.html')
    writeFileSync(source, html)
    // A throwaway profile keeps this from attaching to a Chrome already open.
    execFileSync(chrome, ['--headless', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
      `--user-data-dir=${join(scratch, 'profile')}`, `--window-size=${width},${height}`,
      `--screenshot=${join(web, out)}`, pathToFileURL(source).href], {stdio: 'ignore'})
    console.log(`${out} (${width}x${height})`)
  }
} finally {
  rmSync(scratch, {recursive: true, force: true})
}
