import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import type { Delivery, Health, Target, Task } from './api'
import { clock, date, dayLabel, messageOf, relative, safeUrl, statusLabel } from './api'
import { Button, Empty, Modal, Status } from './components'
import { brand } from './brand'

const KINDS: Record<string, string> = {initial: 'Alert', reminder: 'Reminder', test: 'Test email', verify: 'Email confirmation', reset: 'Password reset', account_exists: 'Account notice', research: 'Research', check: 'Check'}
const kind = (value: string) => KINDS[value] || statusLabel(value)
// Account emails do not count toward the daily limit (notifications.daily_count).
const ACCOUNT_KINDS = ['verify', 'reset', 'account_exists']
const TROUBLE = ['failed', 'uncertain', 'delivery_uncertain']

// Group a newest-first log under day headings in the user's timezone.
function byDay<T>(items: T[], when: (item: T) => string, timezone: string) {
  const groups: [string, T[]][] = []
  for (const item of items) {
    const day = dayLabel(when(item), timezone)
    if (groups.length && groups[groups.length - 1][0] === day) groups[groups.length - 1][1].push(item)
    else groups.push([day, [item]])
  }
  return groups
}

// Plain-text emails keep their links clickable; only http(s) addresses become links.
function linked(text: string): ReactNode[] {
  return text.split(/(https?:\/\/[^\s]+)/g).map((part, index) => {
    const href = index % 2 ? safeUrl(part) : undefined
    return href ? <a key={index} href={href} target="_blank" rel="noopener noreferrer">{part}</a> : <Fragment key={index}>{part}</Fragment>
  })
}

export default function ActivityPage({tasks, deliveries, targets, health, timezone, emailCap, onOpenTarget, onCheck, onTest}: {tasks: Task[]; deliveries: Delivery[]; targets: Target[]; health: Health; timezone: string; emailCap: number; onOpenTarget: (id: string) => void; onCheck: (id: string) => Promise<void>; onTest: () => Promise<void>}) {
  const [tab, setTab] = useState<'emails' | 'tasks'>('emails')
  const [preview, setPreview] = useState<Delivery | null>(null)
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState<string | null>(null)
  const [error, setError] = useState('')
  const workerAlive = health.status === 'ok'
  const watched = targets.filter(t => t.monitoring_status === 'monitoring')
  const issues = targets.filter(t => ['failed', 'unsupported'].includes(t.source_health))
  const next = watched.filter(t => t.next_check_at).sort((a, b) => a.next_check_at!.localeCompare(b.next_check_at!))[0]
  const due = next && new Date(next.next_check_at!).getTime() <= Date.now()
  const today = dayLabel(new Date().toISOString(), timezone)
  const sentToday = deliveries.filter(d => !ACCOUNT_KINDS.includes(d.kind) && ['sent', 'preview', 'sending', 'uncertain'].includes(d.status) && dayLabel(d.sent_at || d.created_at, timezone) === today).length
  const emails = [...deliveries].sort((a, b) => b.created_at.localeCompare(a.created_at))
  const work = [...tasks].sort((a, b) => (b.updated_at || b.created_at).localeCompare(a.updated_at || a.created_at))
  const targetFor = (id: string | null) => targets.find(t => t.id === id)
  const test = async () => {setBusy(true); setError(''); try {await onTest(); setTab('emails')} catch (e) {setError(messageOf(e))} finally {setBusy(false)}}
  const checkAgain = async (id: string) => {setChecking(id); setError(''); try {await onCheck(id)} catch (e) {setError(messageOf(e))} finally {setChecking(null)}}

  return <>
    <header className="page-head"><h1>Activity</h1><div className="page-actions"><Button busy={busy} onClick={() => void test()}>Send a test email</Button></div></header>

    <dl className="vitals" aria-label="Status">
      <div><dt>Worker</dt><dd className={workerAlive ? '' : 'error-text'}>{workerAlive ? 'Running' : 'Stopped'}</dd><dd className="vital-note">{health.worker_last_seen ? `Checked in ${relative(health.worker_last_seen)}` : 'Has not started'}</dd></div>
      <div><dt>Next check</dt><dd>{next ? (due ? 'Due now' : relative(next.next_check_at!).replace(/^in /, 'In ')) : 'None scheduled'}</dd><dd className="vital-note">{next ? `${next.company}, ${clock(next.next_check_at!, timezone)}` : 'No careers pages watched yet'}</dd></div>
      <div><dt>Pages watched</dt><dd>{watched.length}</dd><dd className={`vital-note ${issues.length ? 'error-text' : ''}`}>{issues.length ? `${issues.length} failing` : watched.length ? 'All loading' : 'Approve a page to start'}</dd></div>
      <div><dt>Emails today</dt><dd>{sentToday} of {emailCap}</dd><dd className="vital-note">{health.configuration.email_transport === 'preview' ? 'Previews only' : 'Your daily limit'}</dd></div>
    </dl>

    {!workerAlive && <p className="notice" role="alert"><strong>The worker has stopped.</strong> Your changes are saved; research, checks, and email wait until it runs again.</p>}
    {error && <p className="error-box" role="alert">{error}</p>}

    {issues.length > 0 && <section className="sheet">
      <div className="sheet-bar"><h2 className="sheet-title">{issues.length === 1 ? 'A careers page failed to load' : `${issues.length} careers pages failed to load`}</h2></div>
      <ul className="log">{issues.map(target => <li key={target.id} className="log-row issue">
        <button className="log-main" onClick={() => onOpenTarget(target.id)}>
          <span className="log-text"><strong>{target.company} <span className="muted">{target.role}</span></strong><span className="log-detail">{target.source_error || 'The page could not be read.'}</span></span>
        </button>
        <div className="log-side">{target.last_checked_at && <span className="log-when">Tried {relative(target.last_checked_at)}</span>}<button className="row-step" disabled={checking === target.id} onClick={() => void checkAgain(target.id)}>{checking === target.id ? 'Checking…' : 'Check again'}</button></div>
      </li>)}</ul>
    </section>}

    <section className="sheet">
      <div className="sheet-bar"><div className="tabs" role="tablist" aria-label="Activity"><button role="tab" aria-selected={tab === 'emails'} onClick={() => setTab('emails')}>Emails<span>{deliveries.length}</span></button><button role="tab" aria-selected={tab === 'tasks'} onClick={() => setTab('tasks')}>Checks and research<span>{tasks.length}</span></button></div></div>
      {tab === 'emails' && (emails.length ? <div className="log">{byDay(emails, d => d.created_at, timezone).map(([day, rows]) => <section key={day}>
        <h3 className="log-day">{day}</h3>
        <ul>{rows.map(delivery => {const trouble = TROUBLE.includes(delivery.status) && delivery.error; return <li key={delivery.id} className="log-row">
          <button className="log-main" onClick={() => setPreview(delivery)}>
            <span className="log-time">{clock(delivery.created_at, timezone)}</span>
            <span className="log-text"><strong>{delivery.subject}</strong><span className={trouble ? 'log-detail error-text' : 'log-detail'}>{trouble ? delivery.error : kind(delivery.kind) === delivery.subject ? `To ${delivery.recipient}` : kind(delivery.kind)}</span></span>
          </button>
          <Status value={delivery.status} />
        </li>})}</ul>
      </section>)}</div>
        : <Empty title="No emails yet" description="Alerts, reminders, and account emails show here as they're queued." />)}
      {tab === 'tasks' && (work.length ? <div className="log">{byDay(work, t => t.updated_at || t.created_at, timezone).map(([day, rows]) => <section key={day}>
        <h3 className="log-day">{day}</h3>
        <ul>{rows.map(task => {const target = targetFor(task.target_id); return <li key={task.id} className="log-row">
          <button className="log-main" disabled={!target} onClick={() => target && onOpenTarget(target.id)}>
            <span className="log-time">{clock(task.updated_at || task.created_at, timezone)}</span>
            <span className="log-text"><strong>{kind(task.kind)}{target ? `: ${target.company}` : ''}</strong><span className={task.error ? 'log-detail error-text' : 'log-detail'}>{task.error || (target ? target.role : 'A removed target')}</span></span>
          </button>
          <Status value={task.status} />
        </li>})}</ul>
      </section>)}</div>
        : <Empty title="Nothing has run yet" description="Research and careers-page checks show here as the worker runs them." />)}
    </section>

    {preview && <Modal title={preview.subject} onClose={() => setPreview(null)} wide><div className="modal-body">
      <dl className="facts mail-head"><div><dt>From</dt><dd>{brand.name}</dd></div><div><dt>To</dt><dd>{preview.recipient || 'Your account email'}</dd></div><div><dt>Date</dt><dd>{date(preview.sent_at || preview.created_at, timezone, true)}</dd></div><div><dt>Type</dt><dd>{kind(preview.kind)}</dd></div></dl>
      <div className="mail-body">{linked(preview.plain_body)}</div>
      {TROUBLE.includes(preview.status) && preview.status !== 'failed' && <p className="notice">The mail server may have accepted this before the outcome was recorded. Check the inbox before sending again.</p>}
    </div><div className="modal-footer"><Status value={preview.status} /><Button onClick={() => setPreview(null)}>Close</Button></div></Modal>}
  </>
}
