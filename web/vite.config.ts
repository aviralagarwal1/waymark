import { defineConfig } from 'vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import brand from '../waymark/brand.json'

const escape = (text: string) => text.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;')

// index.html is static, so its title and description are filled from the
// shared brand file here rather than repeated as literals.
const brandHead: Plugin = {
  name: 'brand-head',
  transformIndexHtml: html => html.replaceAll('__BRAND_NAME__', escape(brand.name)).replaceAll('__BRAND_DESCRIPTION__', escape(brand.description)),
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
