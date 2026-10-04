import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Mail } from 'lucide-react'
import { brand } from './brand'
import { SiteFooter, SiteHeader } from './components'

// Laid out like the About pages on Aviral's other products (Scaffold,
// Compline): headshot, name, a few paragraphs on why it exists, then links.
// The copy must hold on the hosted site and a self-hosted install alike, so
// it leaves out research, which runs only where an Anthropic key is set.

// lucide dropped its brand icons, so these glyphs are inline.
const glyph = (d: string) => <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true"><path d={d} /></svg>
const LINKEDIN = 'M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z'
const X = 'M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z'
const GITHUB = 'M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z'

const links: [string, string, ReactNode][] = [
  ['LinkedIn', 'https://www.linkedin.com/in/aviralagarwal05', glyph(LINKEDIN)],
  ['X', 'https://x.com/AviralAgarwal0', glyph(X)],
  ['GitHub', 'https://github.com/aviralagarwal1', glyph(GITHUB)],
  ['Email', 'mailto:aviral.k.agarwal@gmail.com', <Mail size={18} strokeWidth={1.75} aria-hidden="true" />],
]

export default function About() {
  useEffect(() => { document.title = `About · ${brand.name}` }, [])
  return <div className="landing about-page">
    <SiteHeader page="about" />
    <main className="about">
      {/* The name is the heading right below, so the photo needs no alt text. */}
      <img className="about-photo" src="/profile.jpg" alt="" width={480} height={480} decoding="async" />
      <h1>{brand.author}</h1>
      <div className="about-copy">
        <p>I built {brand.name} because the hardest part of a job search shouldn't be knowing when to apply.</p>
        <p>The roles you want most rarely open on your schedule. Catching them means refreshing careers pages or wading through alerts, and by the time you notice, hundreds of people may have applied before you.</p>
        <p>{brand.name} watches the companies and roles you care about. When one opens, you get an email, then reminders until you apply or decide to pass. It won't apply for you. Where you apply and what you say should stay your call. {brand.name} just makes sure you're early.</p>
        <p>If you have feedback or ideas for {brand.name}, I'd love to hear them. You can reach me below or follow my work at <a href={brand.authorUrl} target="_blank" rel="noopener noreferrer">aviralagarwal.com</a>.</p>
      </div>
      <div className="about-links">
        {links.map(([label, href, icon]) => <a key={label} className="about-link" href={href} aria-label={label} title={label} {...(href.startsWith('http') ? {target: '_blank', rel: 'noopener noreferrer'} : {})}>{icon}</a>)}
      </div>
    </main>
    <SiteFooter />
  </div>
}
