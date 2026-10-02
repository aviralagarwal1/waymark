import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode, RefObject } from 'react'
import { brand } from './brand'
import { Mark, SiteFooter, Wordmark } from './components'

const DAY = 86_400_000

// The page's spine: the four things a reader should understand in seconds,
// each shown with the part of the product that does it.
const beats = [
  ['Name the roles you want', 'Add companies and roles by hand or from a spreadsheet, with where and when you want to start.'],
  ['It watches their careers pages', 'Once you approve a page, it is checked on your schedule, and every new posting is compared with what you asked for.'],
  ['Hear the moment one opens', 'One email when a match goes live, then reminders until you apply, snooze, or dismiss it.'],
]

const faq = [
  ['Does it apply for me?', 'No. It tells you when a role opens and links to the posting. Applying is yours.'],
  ['Which careers sites can it watch?', 'Job boards on Greenhouse, Lever, and Ashby, and any careers page that publishes JobPosting structured data. Other sites can be researched, but not watched automatically.'],
  ['What does it cost?', 'The software is free and open source under the MIT license. Research uses your own Anthropic API key, billed by Anthropic, within a monthly budget you set. Watching and email work without a key.'],
  ['What if it can’t find when a role opened?', 'The date stays unknown. You can still watch the careers page, and add the date yourself if you know it.'],
  ['Where does my data go?', 'It stays in your own database. With research turned on, the company and role you enter and the pages it reads are sent to Anthropic. There is no telemetry.'],
  ['How does it email me?', 'Through your own email account, as each match appears or as a daily or weekly digest, with quiet hours and a daily cap.'],
]

const shortDate = (d: Date) => d.toLocaleDateString('en-GB', {day: 'numeric', month: 'short'})

// Example dates sit relative to today, so the page never shows a stale cycle
// (design, Time). Each opened a little after today's date last year, which is
// why it is worth watching now.
function exampleDates() {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const lastYear = (days: number) => { const d = new Date(today.getTime() + days * DAY); return new Date(d.getFullYear() - 1, d.getMonth(), d.getDate()) }
  // Harvey, Polymarket, and Sierra opened 70, 38, and 5 days past today's
  // date last year. Each gap is over 31 days, so they always fall in three
  // different months, and the closer to the open role, the sooner it opened.
  return {harvey: lastYear(70), polymarket: lastYear(38), sierra: lastYear(5)}
}

// Faint contour lines behind the page. Generated rather than drawn so the
// file stays small; fixed seeds keep the terrain the same on every load.
function contourPaths(cx: number, cy: number, rings: number, step: number, seed: number) {
  return Array.from({length: rings}, (_, k) => {
    const R = (k + 1) * step
    let d = ''
    for (let i = 0; i <= 96; i++) {
      const t = i / 96 * Math.PI * 2
      const r = R * (1 + 0.12 * Math.sin(3 * t + seed + k * 0.15) + 0.07 * Math.sin(5 * t + seed * 2 - k * 0.1))
      d += `${i ? 'L' : 'M'}${(cx + r * Math.cos(t) * 1.35).toFixed(1)} ${(cy + r * Math.sin(t)).toFixed(1)}`
    }
    return {d: `${d}Z`, major: (k + 1) % 5 === 0}
  })
}
const terrain = [...contourPaths(1060, 180, 26, 26, 0.6), ...contourPaths(180, 780, 14, 30, 2.1)]

// The route climbs from the bottom left to the open role at the top right.
// Waypoints are HTML so their labels stay legible at any width; the path is
// SVG with non-scaling strokes so its dots keep their size. Labels sit to the
// right of each waypoint, clear of the path. Under the centered hero the
// figure is wide, so the route spreads across it; on narrow screens it keeps
// to the left so the labels still fit.
const ROUTE_WIDE = 'M2 112 C 4 102, 5 94, 6 88 S 19 72, 24 68 S 37 52, 42 48 S 55 32, 60 28 S 73 12, 78 8'
const ROUTE_NARROW = 'M-2 112 C 1 102, 2 96, 3 90 S 11 74, 15 70 S 23 54, 27 50 S 35 34, 39 30 S 47 14, 51 10'

// A reveal's delay, read by the CSS transition.
const delay = (ms: number) => ({'--d': `${ms}ms`}) as CSSProperties

// Motion is opt-in: the class that hides content before it reveals is added
// only when the reader has not asked for reduced motion and the browser can
// observe scrolling, so the page is fully visible without it. Layout effect,
// so the hidden state lands before the first paint rather than flashing.
// Reveals are marked with data-shown, not a class, because React owns className
// and would drop an added class the next time it re-renders the element.
function useMotion(root: RefObject<HTMLDivElement | null>) {
  useLayoutEffect(() => {
    const el = root.current
    if (!el || !('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    el.classList.add('motion')
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) { entry.target.setAttribute('data-shown', ''); observer.unobserve(entry.target) }
    }, {rootMargin: '0px 0px -8% 0px', threshold: 0})
    el.querySelectorAll('[data-reveal]').forEach(node => observer.observe(node))
    let frame = 0
    const onScroll = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => el.style.setProperty('--scroll', String(window.scrollY))) }
    window.addEventListener('scroll', onScroll, {passive: true})
    return () => { observer.disconnect(); window.removeEventListener('scroll', onScroll); cancelAnimationFrame(frame) }
  }, [root])
}

// The amber walks the beats once, the first time the list comes into view,
// lighting each in turn and leaving it lit, so all four end up glowing. It is
// not tied to scroll position, so scrolling back never undoes it and it cannot
// jitter. With reduced motion, or without an observer, all four start lit.
const STEP_PACE_MS = 900
function useWalkedSteps(list: RefObject<HTMLOListElement | null>, count: number) {
  const [active, setActive] = useState(-1)
  useEffect(() => {
    const el = list.current
    if (!el || !('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setActive(count - 1); return }
    const timers: number[] = []
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return
      observer.disconnect()
      for (let i = 0; i < count; i++) timers.push(window.setTimeout(() => setActive(i), 300 + i * STEP_PACE_MS))
    }, {rootMargin: '0px 0px -25% 0px'})
    observer.observe(el)
    return () => { observer.disconnect(); timers.forEach(clearTimeout) }
  }, [list, count])
  return active
}

// Product panels, one per beat. They show fields the product really has
// (targets, source checks, the alert email as the worker writes it) for the
// four companies on the hero trail, so the page tells one story. Every
// address uses the reserved .example domain, and the section is captioned as
// illustrative, so nothing reads as a fact about a real company's hiring.
function Panel({title, meta, children}: {title: string; meta?: string; children: ReactNode}) {
  return <div className="panel"><div className="panel-head"><strong>{title}</strong>{meta && <span>{meta}</span>}</div>{children}</div>
}

// Each company's own icon in a small tile, served from web/public/logos so the
// page makes no outside requests. Taken from each company's site on
// 2026-09-30 (Sierra's SVG pinned to its own dark-mode green, since this page
// is always dark). Waymark's row uses its mark; a company without a file gets its
// initial. Decorative: the name sits right beside it.
const LOGOS: Record<string, string> = {Figma: '/logos/figma.svg', Harvey: '/logos/harvey.png', Polymarket: '/logos/polymarket.png', Sierra: '/logos/sierra.svg'}
function Logo({name}: {name: string}) {
  return <span className="logo-tile" aria-hidden="true">{name === brand.name ? <Mark size={18} /> : LOGOS[name] ? <img src={LOGOS[name]} alt="" width={18} height={18} /> : name[0]}</span>
}

function WatchlistPanel() {
  const start = new Date().getFullYear() + 1
  const rows = [['Sierra', 'Agent Strategist'], ['Polymarket', 'Quantitative Trader'], ['Harvey', 'Legal Operations'], ['Figma', 'Product Designer']]
  return <Panel title="Watchlist" meta={`${rows.length} targets`}>
    <table className="panel-table"><thead><tr><th>Company</th><th>Role</th><th>Start</th></tr></thead>
      <tbody>{rows.map(([company, role]) => <tr key={company}><td><span className="company"><Logo name={company} /><span>{company}<span className="cell-sub">{role}</span></span></span></td><td>{role}</td><td>Summer {start}</td></tr>)}</tbody></table>
  </Panel>
}

function ChecksPanel() {
  const rows = [
    {company: 'Sierra', source: 'careers.sierra.example', checked: '12 minutes ago', result: '1 new match', live: true},
    {company: 'Polymarket', source: 'careers.polymarket.example', checked: '2 hours ago', result: '2 new postings, neither matches', live: false},
    {company: 'Harvey', source: 'careers.harvey.example', checked: '2 hours ago', result: 'No new postings', live: false},
    {company: 'Figma', source: 'No source approved', checked: 'Not watched', result: 'Add a careers page to watch it', live: false},
  ]
  return <Panel title="Sources" meta="Checked every 6 hours">
    <ul className="checks">{rows.map(row => <li key={row.company}>
      <span className="company"><Logo name={row.company} /><span><strong>{row.company}</strong><span className={row.source.includes('.') ? 'source' : 'blank'}>{row.source}</span></span></span>
      <div><span>{row.checked}</span><span className={row.live ? 'now' : ''}>{row.result}</span></div>
    </li>)}</ul>
  </Panel>
}

function EmailPanel() {
  return <Panel title="Now open: Agent Strategist at Sierra" meta="Email, 12 minutes ago">
    <div className="email">
      <p>A role you're watching just opened.</p>
      <div className="email-match">
        <strong>Agent Strategist, Sierra</strong>
        <span>United States</span>
        <span className="source">careers.sierra.example/jobs/agent-strategist</span>
      </div>
      <p className="blank">Found on the careers page; it may have been posted a little earlier.</p>
    </div>
  </Panel>
}

const beatPanels = [WatchlistPanel, ChecksPanel, EmailPanel]

function Trail() {
  const {harvey, polymarket, sierra} = exampleDates()
  // Real employers make the example recognizable, so its dates are labelled an
  // illustration below: none of them is a claim about that company's hiring.
  // The open role at the top is Waymark's own.
  const points = [
    {x: 6, y: 88, nx: 3, ny: 90, open: false, name: 'Figma', role: 'Product Designer', status: 'No past opening found'},
    {x: 24, y: 68, nx: 15, ny: 70, open: false, name: 'Harvey', role: 'Legal Operations', status: `Opened ${shortDate(harvey)} last year`},
    {x: 42, y: 48, nx: 27, ny: 50, open: false, name: 'Polymarket', role: 'Quantitative Trader', status: `Opened ${shortDate(polymarket)} last year`},
    {x: 60, y: 28, nx: 39, ny: 30, open: false, name: 'Sierra', role: 'Agent Strategist', status: `Opened ${shortDate(sierra)} last year`},
    {x: 78, y: 8, nx: 51, ny: 10, open: true, name: brand.name, role: 'Builder', status: 'Open right now'},
  ]
  return <figure className="trail" data-reveal style={delay(250)} aria-label="An illustrated watchlist: five roles along a route">
    {[['wide', ROUTE_WIDE], ['narrow', ROUTE_NARROW]].map(([layout, route]) => <svg key={layout} className={`trail-path ${layout}`} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <path d={route} className="trail-glow" vectorEffect="non-scaling-stroke" />
      <path d={route} className="trail-dots" vectorEffect="non-scaling-stroke" />
    </svg>)}
    <ol>
      {points.map((p, i) => <li key={p.name} className="waypoint" style={{'--x': `${p.x}%`, '--y': `${p.y}%`, '--nx': `${p.nx}%`, '--ny': `${p.ny}%`, ...delay(700 + i * 220)} as CSSProperties}>
        <i className={`waypoint-mark${p.open ? ' open' : ''}`} aria-hidden="true" />
        <span><strong>{p.name}</strong><span>{p.role}</span><span className={`waypoint-status${p.open ? ' now' : ''}`}>{p.status}</span></span>
      </li>)}
    </ol>
  </figure>
}

// The hero's copy comes from brand.json; its line breaks are set where the
// words read best (an inverted pyramid under the headline). If the copy
// changes and the break point is gone, the browser wraps it instead.
const splitAfter = (text: string, marker: string) => {
  const at = text.indexOf(marker)
  return at < 0 ? [text, ''] : [text.slice(0, at + marker.length), text.slice(at + marker.length)]
}
const headline = splitAfter(brand.tagline, 'job ')
const lede = splitAfter(brand.description, 'cycles, ')

export default function Landing() {
  const root = useRef<HTMLDivElement>(null)
  const routeList = useRef<HTMLOListElement>(null)
  useMotion(root)
  const activeStep = useWalkedSteps(routeList, beats.length)
  return <div className="landing" ref={root}>
    <svg className="terrain" viewBox="0 0 1280 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {terrain.map((c, i) => <path key={i} d={c.d} className={c.major ? 'major' : ''} />)}
    </svg>
    <header className="landing-header">
      <a href="/" className="landing-home" aria-label={`${brand.name} home`}><Wordmark name={brand.name} /></a>
      <nav aria-label="Main">
        <a href="/signin" className="landing-button compact">Sign in</a>
        <a href="/signup" className="landing-button primary compact">Create account</a>
      </nav>
    </header>

    <main>
      <section className="landing-hero">
        <div className="landing-hero-copy">
          <h1 data-reveal>{headline[0]}{headline[1] && <><br />{headline[1]}</>}</h1>
          <p data-reveal style={delay(120)}>{lede[0]}{lede[1] && <><br className="wide-break" />{lede[1]}</>}</p>
          <div className="landing-actions" data-reveal style={delay(220)}>
            <a href="/signup" className="landing-button primary">Create account</a>
          </div>
        </div>
        <Trail />
      </section>

      <section id="how" className="beats-section">
        <h2 className="section-label" data-reveal>How it works</h2>
        <ol className="beats" ref={routeList}>
          {beats.map(([title, text], i) => {
            const Product = beatPanels[i]
            return <li key={title} className={i < activeStep ? 'walked' : i === activeStep ? 'here' : ''} aria-current={i === activeStep ? 'step' : undefined}>
              <span className="beat-mark" aria-hidden="true">{i + 1}</span>
              <div className="beat-copy" data-reveal><h3>{title}</h3><p>{text}</p></div>
              <div className="beat-product" data-reveal style={delay(120)}><Product /></div>
            </li>
          })}
        </ol>
        <p className="beats-caption">Companies and job applications are illustrative.</p>
      </section>

      <section id="faq" className="landing-section">
        <h2 data-reveal>Frequently asked questions</h2>
        <div className="landing-faq">
          {faq.map(([q, a], i) => <details key={q} data-reveal style={delay(i * 60)}><summary>{q}</summary><p>{a}</p></details>)}
        </div>
      </section>
    </main>

    <SiteFooter />
  </div>
}
