import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { api, messageOf } from './api'
import { brand } from './brand'
import { Field, Input, Wordmark } from './components'

export type AuthPage = 'signin' | 'signup' | 'verify' | 'forgot' | 'reset'

const PASSWORD_MIN = 10
const post = <T,>(path: string, body: unknown) => api<T>(path, {method: 'POST', body: JSON.stringify(body)})
const token = () => new URLSearchParams(window.location.search).get('token') || ''
// After signing in, return to the page that asked for it. Only workspace
// paths are honored, so a crafted link cannot send the reader off-site.
const goToApp = () => {
  const next = new URLSearchParams(window.location.search).get('next') || ''
  window.location.href = /^\/app(\/|$)/.test(next) ? next : '/app'
}

function Shell({title, lede, children}: {title: string; lede?: string; children?: ReactNode}) {
  return <div className="landing auth">
    <header className="landing-header"><a href="/" className="landing-home" aria-label={`${brand.name} home`}><Wordmark name={brand.name} /></a></header>
    <main className="auth-main">
      <h1>{title}</h1>
      {lede && <p className="auth-lede">{lede}</p>}
      {children}
    </main>
  </div>
}

// A new password's length rule stays out of sight until it matters: a short
// submission shakes the field and shows the rule, which fades after a few
// seconds or as soon as the password is long enough. `nudge` counts attempts.
const RULE_MS = 3500
function NewPassword({label, value, onChange, nudge}: {label: string; value: string; onChange: (value: string) => void; nudge: number}) {
  const [shaking, setShaking] = useState(false)
  const [showRule, setShowRule] = useState(false)
  useEffect(() => {
    if (!nudge) return
    setShaking(true); setShowRule(true)
    const id = window.setTimeout(() => setShowRule(false), RULE_MS)
    return () => window.clearTimeout(id)
  }, [nudge])
  useEffect(() => { if (value.length >= PASSWORD_MIN) setShowRule(false) }, [value])
  return <Field label={label}>
    <div className={`shake-wrap${shaking ? ' shaking' : ''}`} onAnimationEnd={() => setShaking(false)}>
      <Input type="password" autoComplete="new-password" required value={value} onChange={e => onChange(e.target.value)} aria-invalid={showRule} aria-describedby="password-rule" />
    </div>
    <small id="password-rule" className={`field-rule${showRule ? ' visible' : ''}`} role="status">{showRule ? `Must be at least ${PASSWORD_MIN} characters` : ''}</small>
  </Field>
}

// Shown after sign-up, resend, and forgot. The server answers the same way
// whether or not an account exists, so this never says which it was.
function CheckEmail({email, onResend}: {email: string; onResend?: () => Promise<void>}) {
  const [note, setNote] = useState('')
  return <div className="auth-sent">
    <p>If <strong>{email}</strong> can receive it, a link is on its way. It works once and expires soon.</p>
    {onResend && <button type="button" className="auth-link" onClick={async () => { try { await onResend(); setNote('Sent another link.') } catch (e) { setNote(messageOf(e)) } }}>Send another link</button>}
    {note && <p className="auth-note" role="status">{note}</p>}
  </div>
}

function SignIn() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [unverified, setUnverified] = useState(false)
  const [busy, setBusy] = useState(false)
  const [resent, setResent] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError(''); setUnverified(false)
    try { await post('/auth/login', {email, password}); goToApp() }
    catch (err) { const message = messageOf(err); setError(message); setUnverified(message.startsWith('Confirm your email')) }
    finally { setBusy(false) }
  }
  if (resent) return <Shell title="Check your email"><CheckEmail email={email} /></Shell>
  return <Shell title="Sign in">
    <form className="auth-form" onSubmit={submit} noValidate>
      <Field label="Email"><Input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></Field>
      <Field label="Password"><Input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></Field>
      {error && <p className="auth-error" role="alert">{error}</p>}
      {unverified && <button type="button" className="auth-link" onClick={async () => { await post('/auth/resend', {email}); setResent(true) }}>Send a new confirmation link</button>}
      <button type="submit" className="landing-button primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
    <p className="auth-alt"><a href="/forgot">Forgot your password?</a></p>
    <p className="auth-alt">New to {brand.name}? <a href="/signup">Create an account</a></p>
  </Shell>
}

function SignUp() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [nudge, setNudge] = useState(0)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError('')
    if (password.length < PASSWORD_MIN) { setNudge(n => n + 1); return }
    setBusy(true)
    try {
      const result = await post<{status: string}>('/auth/signup', {email, password})
      if (result.status === 'signed_in') goToApp(); else setSent(true)
    } catch (err) { setError(messageOf(err)) } finally { setBusy(false) }
  }
  if (sent) return <Shell title="Confirm your email" lede="Open the link we sent to finish creating your account."><CheckEmail email={email} onResend={async () => { await post('/auth/resend', {email}) }} /></Shell>
  return <Shell title="Create your account" lede="Track the roles you want, and hear the moment they open.">
    <form className="auth-form" onSubmit={submit} noValidate>
      <Field label="Email"><Input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></Field>
      <NewPassword label="Password" value={password} onChange={setPassword} nudge={nudge} />
      {error && <p className="auth-error" role="alert">{error}</p>}
      <button type="submit" className="landing-button primary" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
    </form>
    <p className="auth-alt">Already have an account? <a href="/signin">Sign in</a></p>
  </Shell>
}

function Verify() {
  const [error, setError] = useState('')
  useEffect(() => {
    post('/auth/verify', {token: token()}).then(goToApp).catch(err => setError(messageOf(err)))
  }, [])
  if (!error) return <Shell title="Confirming your email…" />
  return <Shell title="That link didn't work" lede={error}>
    <p className="auth-alt"><a href="/signin">Sign in</a> to request a new confirmation link.</p>
  </Shell>
}

function Forgot() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try { await post('/auth/forgot', {email}); setSent(true) } catch (err) { setError(messageOf(err)) } finally { setBusy(false) }
  }
  if (sent) return <Shell title="Check your email" lede="Open the link to choose a new password."><CheckEmail email={email} /></Shell>
  return <Shell title="Reset your password" lede="We'll email you a link to choose a new one.">
    <form className="auth-form" onSubmit={submit} noValidate>
      <Field label="Email"><Input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></Field>
      {error && <p className="auth-error" role="alert">{error}</p>}
      <button type="submit" className="landing-button primary" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</button>
    </form>
    <p className="auth-alt"><a href="/signin">Back to sign in</a></p>
  </Shell>
}

function Reset() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [nudge, setNudge] = useState(0)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError('')
    if (password.length < PASSWORD_MIN) { setNudge(n => n + 1); return }
    setBusy(true)
    try { await post('/auth/reset', {token: token(), password}); goToApp() } catch (err) { setError(messageOf(err)) } finally { setBusy(false) }
  }
  return <Shell title="Choose a new password" lede="This signs you out on every other device.">
    <form className="auth-form" onSubmit={submit} noValidate>
      <NewPassword label="New password" value={password} onChange={setPassword} nudge={nudge} />
      {error && <p className="auth-error" role="alert">{error}</p>}
      <button type="submit" className="landing-button primary" disabled={busy}>{busy ? 'Saving…' : 'Save and sign in'}</button>
    </form>
    {error && <p className="auth-alt"><a href="/forgot">Request a new link</a></p>}
  </Shell>
}

export default function Auth({page}: {page: AuthPage}) {
  return {signin: <SignIn />, signup: <SignUp />, verify: <Verify />, forgot: <Forgot />, reset: <Reset />}[page]
}
