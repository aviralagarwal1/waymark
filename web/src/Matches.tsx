import { useState } from 'react'
import type { Match } from './api'
import { date, dateKind, messageOf } from './api'
import { Button, Empty, ExternalLink, Field, Input, Modal, SearchBox } from './components'

type View = 'new' | 'applied' | 'snoozed' | 'dismissed' | 'all'

export default function Matches({matches, timezone, onSave, onOpenTarget}: {matches: Match[]; timezone: string; onSave: (match: Match, status: Match['status'], until?: string) => Promise<void>; onOpenTarget: (id: string) => void}) {
  const [view, setView] = useState<View>('new')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [snooze, setSnooze] = useState<Match | null>(null)
  const [snoozeDays, setSnoozeDays] = useState(3)
  const [error, setError] = useState('')
  const count = (v: View) => v === 'all' ? matches.length : matches.filter(m => m.status === v).length
  const filtered = matches.filter(m => (view === 'all' || m.status === view) && `${m.company} ${m.title} ${m.location}`.toLowerCase().includes(search.toLowerCase())).sort((a, b) => b.first_seen_at.localeCompare(a.first_seen_at))
  const save = async (match: Match, status: Match['status'], until?: string) => {setBusy(match.id); setError(''); try {await onSave(match, status, until); if (status === 'snoozed') setSnooze(null)} catch (e) {setError(messageOf(e))} finally {setBusy(null)}}
  const tabs: [View, string][] = [['new', 'New'], ['applied', 'Applied'], ['snoozed', 'Snoozed'], ['dismissed', 'Dismissed'], ['all', 'All']]
  return <>
    <header className="page-head"><h1>Openings</h1></header>
    <section className="sheet">
      <div className="sheet-bar">
        <div className="tabs" role="tablist" aria-label="Filter openings">{tabs.map(([value, label]) => <button key={value} role="tab" aria-selected={view === value} onClick={() => setView(value)}>{label}<span>{count(value)}</span></button>)}</div>
        <div className="sheet-tools"><SearchBox value={search} onChange={setSearch} placeholder="Search" /></div>
      </div>
      {error && !snooze && <div className="error-box" role="alert">{error}</div>}
      {!filtered.length ? <Empty title={view === 'new' ? 'No new openings' : 'Nothing here'} description={view === 'new' ? 'When a page you watch posts a role that matches, it appears here and in your email.' : search ? 'No opening matches that search.' : 'Openings move here as you mark them.'} action={search ? <Button onClick={() => setSearch('')}>Clear search</Button> : undefined} />
        : <ol className="openings">{filtered.map(match => <li className={`opening ${match.closed ? 'closed' : ''}`} key={match.id}>
          <div className="opening-main">
            <h2><ExternalLink url={match.url}>{match.title}</ExternalLink></h2>
            <p className="opening-meta"><button className="link-button" onClick={() => onOpenTarget(match.target_id)}>{match.company}</button><span>{match.location || 'Location not stated'}</span><span>Found {date(match.first_seen_at, timezone)}</span>{match.published_at && <span>{dateKind(match.date_meaning) || 'Dated'} {date(match.published_at, timezone)}</span>}{match.closed && <span>Closed</span>}{match.status === 'snoozed' && match.snoozed_until && <span>Snoozed until {date(match.snoozed_until, timezone, true)}</span>}</p>
            {/* A clean match needs no explanation; the matcher's note matters only when it is unsure. */}
            {match.reason.startsWith('Needs review') && <p className="opening-reason">{match.reason.replace(/^Needs review:\s*/, 'Check before applying: ')}</p>}
          </div>
          <div className="opening-actions">
            {match.status !== 'new' && <Button variant="ghost" busy={busy === match.id} onClick={() => void save(match, 'new')}>Move to new</Button>}
            {match.status === 'new' && <><Button variant="ghost" busy={busy === match.id} onClick={() => void save(match, 'dismissed')}>Dismiss</Button><Button variant="ghost" disabled={busy === match.id || match.closed} onClick={() => {setSnooze(match); setError('')}}>Snooze</Button></>}
            {match.status !== 'applied' && <Button busy={busy === match.id} onClick={() => void save(match, 'applied')}>Mark applied</Button>}
          </div>
        </li>)}</ol>}
    </section>
    {snooze && <Modal title="Snooze reminders" subtitle={`${snooze.title}, ${snooze.company}`} onClose={() => setSnooze(null)}><form onSubmit={e => {e.preventDefault(); void save(snooze, 'snoozed', new Date(Date.now() + snoozeDays * 86400000).toISOString())}}><div className="modal-body"><Field label="Snooze for (days)" hint={`Reminders resume ${date(new Date(Date.now() + snoozeDays * 86400000).toISOString(), timezone, true)}. Checks continue meanwhile.`}><Input required type="number" min="1" max="365" value={snoozeDays} onChange={e => setSnoozeDays(Number(e.target.value))} /></Field>{error && <p className="error-box" role="alert">{error}</p>}</div><div className="modal-footer"><Button onClick={() => setSnooze(null)}>Cancel</Button><Button type="submit" variant="primary" busy={busy === snooze.id}>Snooze</Button></div></form></Modal>}
  </>
}
