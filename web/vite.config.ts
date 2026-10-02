import { defineConfig } from 'vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import brand from '../waymark/brand.json'

const escape = (text: string) => text.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;')

// index.html is static, so its title and description are filled from the
// shared brand file here rather than repeated as literals. __APP_BASE_URL__ is
// left for the server, which knows each install's public origin; the dev
// server has none, so its preview URLs stay relative.
const brandHead: Plugin = {
  name: 'brand-head',
  transformIndexHtml: (html, context) => {
    const filled = html.replaceAll('__BRAND_NAME__', escape(brand.name)).replaceAll('__BRAND_TAGLINE__', escape(brand.tagline))
      .replaceAll('__BRAND_DESCRIPTION__', escape(brand.description))
    return context.server ? filled.replaceAll('__APP_BASE_URL__', '') : filled
  },
  // The manifest names the app for "Add to Home Screen", from the same file.
  // No standalone display: an iOS home-screen app keeps cookies apart from
  // Safari, where confirmation and reset links open, so it would sign people
  // in twice.
  generateBundle() {
    this.emitFile({type: 'asset', fileName: 'site.webmanifest', source: JSON.stringify({
      name: brand.name, short_name: brand.name, description: brand.description,
      start_url: '/app', background_color: '#0b1016', theme_color: '#0b1016',
      icons: [192, 512].map(size => ({src: `/icon-${size}.png`, sizes: `${size}x${size}`, type: 'image/png', purpose: 'any maskable'})),
    }, null, 2)})
  },
}

export default defineConfig({
  plugins: [react(), brandHead],
  server: {
    // Keep the browser's Host header when proxying. The API refuses writes whose
    // Origin differs from the host they were sent to; the shorthand proxy form
    // rewrites Host to the API's own address, which made every dev write a 403.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
    // The brand file sits in the Python package, outside the web root.
    fs: { allow: ['.', '../waymark/brand.json'] },
  },
  build: { outDir: 'dist', sourcemap: false },
})
