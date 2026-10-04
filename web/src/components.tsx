import { useEffect, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { ArrowUpRight, Check, ChevronDown, LoaderCircle, Search, X } from 'lucide-react'
import { safeUrl, statusLabel } from './api'
import { brand } from './brand'

export function Button({children, variant = 'secondary', busy, className = '', ...props}: ButtonHTMLAttributes<HTMLButtonElement> & {variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; busy?: boolean}) {
  return <button type="button" className={`button ${variant} ${className}`} {...props} disabled={props.disabled || busy}>{busy && <LoaderCircle size={15} className="spin" />}{children}</button>
}
// The mark is a W walked as a trail: a faint path, dotted footsteps along it,
// and a lit waymark where it ends. Lines take the text color so the mark
// works on any surface; only the waymark carries the brand color.
const TRAIL_W = 'M3 6C6 14 8.5 22 12 22S16.5 11 20 11 24.5 22 28 22 34 14 37 6'
export function Mark({size = 34}: {size?: number}) {
  return <svg className="mark" width={size} height={size * 0.7} viewBox="0 0 40 28" aria-hidden="true">
    <path d={TRAIL_W} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    <path d={TRAIL_W} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeDasharray="0.1 4.4" />
    <circle cx="37" cy="6" r="3.5" fill="var(--now)" />
  </svg>
}
export function Wordmark({name}: {name: string}) {
  return <span className="wordmark"><Mark /><span className="wordmark-name">{name}</span></span>
}
// The public pages' header. The account pages keep only the wordmark, since
// offering "Sign in" on the sign-in page leads nowhere. On narrow phones the
// three links leave no room for the name, so the mark stands alone there.
export function SiteHeader({page}: {page?: 'about'}) {
  return <header className="landing-header">
    <a href="/" className="landing-home site-home" aria-label={`${brand.name} home`}><Wordmark name={brand.name} /></a>
    <nav aria-label="Main">
      <a href="/about" className="landing-nav-link" aria-current={page === 'about' ? 'page' : undefined}>About</a>
      <a href="/signin" className="landing-button compact">Sign in</a>
      <a href="/signup" className="landing-button primary compact">Create account</a>
    </nav>
  </header>
}
// Matches the footer on Aviral's other products (Compline), so they read as a family.
export function SiteFooter() {
  return <footer className="site-foot">
    <span>{brand.name}</span>
    <span>Built by <a href={brand.authorUrl} target="_blank" rel="noopener noreferrer">{brand.author}</a> · Source on <a href={brand.repoUrl} target="_blank" rel="noopener noreferrer">GitHub</a> · © {new Date().getFullYear()}</span>
  </footer>
}
// A state in words. Only failures take a color, so a red word always means
// something needs attention; everything else reads as text.
export function Status({value}: {value: string}) {
  const tone = ['failed', 'delivery_uncertain', 'uncertain', 'unsupported'].includes(value) ? 'red'
    : ['idle', 'unknown', 'canceled', 'stale', 'dismissed', 'draft', 'paused', 'preview', 'done', 'sent'].includes(value) ? 'quiet' : ''
  return <span className={`status ${tone}`}>{statusLabel(value)}</span>
}
export function ExternalLink({url, children, className = ''}: {url: string | undefined | null; children?: ReactNode; className?: string}) {
  const href = safeUrl(url)
  if (!href) return <span className={`muted ${className}`}>{children || 'No source yet'}</span>
  return <a className={`external-link ${className}`} href={href} target="_blank" rel="noopener noreferrer">{children || new URL(href).hostname.replace(/^www\./, '')}<ArrowUpRight size={13} aria-label="opens in a new tab" /></a>
}
// The hint sits outside the <label>, so a control's accessible name is its
// label alone rather than the label plus every word of help text.
export function Field({label, hint, children, className = ''}: {label: string; hint?: string; children: ReactNode; className?: string}) {
  return <div className={`field ${className}`}><label><span>{label}</span>{children}</label>{hint && <small>{hint}</small>}</div>
}
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {return <input className="input" {...props} />}
export function Select({children, ...props}: SelectHTMLAttributes<HTMLSelectElement>) {return <span className="select-wrap"><select className="input" {...props}>{children}</select><ChevronDown size={14} /></span>}
export function Empty({title, description, action}: {title: string; description: string; action?: ReactNode}) {
  return <div className="empty"><h3>{title}</h3><p>{description}</p>{action}</div>
}
export function SearchBox({value, onChange, placeholder = 'Search companies, roles, locations…'}: {value: string; onChange: (s: string) => void; placeholder?: string}) {
  return <div className="search-box"><Search size={17} /><input aria-label={placeholder} placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)} />{value && <button aria-label="Clear search" onClick={() => onChange('')}><X size={14} /></button>}</div>
}
export function Modal({title, subtitle, onClose, children, wide = false, drawer = false}: {title: string; subtitle?: string; onClose: () => void; children: ReactNode; wide?: boolean; drawer?: boolean}) {
  const ref = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const timer = window.setTimeout(() => ref.current?.querySelector<HTMLElement>('input, select, textarea, button, a[href], [tabindex="0"]')?.focus(), 0)
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {event.preventDefault(); close.current(); return}
      if (event.key !== 'Tab') return
      const elements = [...(ref.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex="0"]') || [])].filter(el => el.getClientRects().length)
      const first = elements[0]; const last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus()}
      else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus()}
    }
    document.addEventListener('keydown', handler)
    return () => {window.clearTimeout(timer); document.removeEventListener('keydown', handler); document.body.style.overflow = previousOverflow; previous?.focus()}
  }, [])
  return <div className={`modal-backdrop ${drawer ? 'drawer-backdrop' : ''}`} onMouseDown={e => {if (e.target === e.currentTarget) onClose()}}><div ref={ref} role="dialog" aria-modal="true" aria-labelledby="dialog-title" className={`modal ${wide ? 'wide' : ''} ${drawer ? 'drawer' : ''}`}><div className="modal-heading"><div><h2 id="dialog-title">{title}</h2>{subtitle && <p>{subtitle}</p>}</div><Button variant="ghost" onClick={onClose} aria-label="Close dialog"><X size={20} /></Button></div>{children}</div></div>
}
export function Editable({value, label, onSave, type = 'text', placeholder = 'Add…'}: {value: string; label: string; onSave: (value: string) => Promise<void>; type?: string; placeholder?: string}) {
  const [draft, setDraft] = useState(value)
  const [busy, setBusy] = useState(false)
  const skip = useRef(false)
  const active = useRef(false)
  useEffect(() => {if (!active.current) setDraft(value)}, [value])
  const save = async () => {
    active.current = false
    if (skip.current) {skip.current = false; setDraft(value); return}
    if (draft.trim() === value) return
    setBusy(true)
    try {await onSave(draft.trim())} catch {setDraft(value)} finally {setBusy(false)}
  }
  return <span className="editable-wrap"><input aria-label={label} type={type} className="editable" value={draft} disabled={busy} placeholder={placeholder}
    onChange={e => setDraft(e.target.value)} onFocus={() => {active.current = true}} onBlur={() => void save()}
    onKeyDown={e => {if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') {skip.current = true; e.currentTarget.blur()}}} />{busy && <LoaderCircle size={12} className="spin" />}</span>
}
export function CheckBox({checked, onChange, label}: {checked: boolean; onChange: (value: boolean) => void; label: string}) {
  return <label className="check-label"><input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} /><span className="check-visual">{checked && <Check size={12} strokeWidth={3} />}</span><span>{label}</span></label>
}
