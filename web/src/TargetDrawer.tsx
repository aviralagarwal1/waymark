import { useEffect, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import type { Evidence, Match, Target, TargetInput } from './api'
import { api, date, dateKind, editableTarget, messageOf, nextCohortYear, statusLabel } from './api'
import { Button, CheckBox, Empty, ExternalLink, Field, Input, Modal, Select, Status } from './components'
import { TargetFields } from './TargetForm'

type Props = {target: Target; matches: Match[]; timezone: string; onClose: () => void; onPatch: (patch: Partial<TargetInput>) => Promise<void>; onAction: (action: 'research' | 'approve' | 'check', includeExisting?: boolean) => Promise<void>; onDelete: () => Promise<void>}
export default function TargetDrawer({target, matches, timezone, onClose, onPatch, onAction, onDelete}: Props) {
  const [tab, setTab] = useState('evidence')
  const [draft, setDraft] = useState<TargetInput>(() => editableTarget(target))
  const [evidence, setEvidence] = useState<Evidence[]>([])
  const [evidenceLoading, setEvidenceLoading] = useState(true)
  const [evidenceError, setEvidenceError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [includeExisting, setIncludeExisting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [discard, setDiscard] = useState(false)
  const [saved, setSaved] = useState(false)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let cancelled = false
    setEvidenceLoading(true)
    api<Evidence[]>(`/targets/${target.id}/evidence`).then(value => {if (!cancelled) {setEvidence(value); setEvidenceError('')}}).catch(e => {if (!cancelled) setEvidenceError(messageOf(e))}).finally(() => {if (!cancelled) setEvidenceLoading(false)})
    return () => {cancelled = true}
  }, [target.id, target.research_status, reload])
  useEffect(() => {if (!dirty) setDraft(editableTarget(target))}, [target, dirty])
  const run = async (name: string, fn: () => Promise<void>) => {setBusy(name); setError(''); try {await fn()} catch (e) {setError(messageOf(e))} finally {setBusy('')}}
  const researchBusy = ['queued', 'researching'].includes(target.research_status)
  const proposed = target.source_url || target.proposed_source_url
  const change = (patch: Partial<TargetInput>) => {setDirty(true); setSaved(false); setDraft(d => ({...d, ...patch}))}
  return <Modal title={target.company} subtitle={target.role} onClose={() => {if (busy) return; if (dirty) setDiscard(true); else onClose()}} drawer>
    <p className="drawer-meta">{[target.location || 'Anywhere', target.start_period].filter(Boolean).join(', ')}</p>
    <div className="drawer-tabs" role="tablist" aria-label="Target details">{[['evidence', 'Overview'], ['matches', 'Openings'], ['edit', 'Settings']].map(([value, label]) => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>{label}{value === 'matches' && matches.length > 0 && <span className="tab-count">{matches.length}</span>}{value === 'edit' && dirty && <span className="unsaved-mark">, unsaved</span>}</button>)}</div>
    <div className="drawer-content">
      {discard && <div className="soft-note" role="alert"><div><p>Discard your unsaved target changes?</p><div className="button-group"><Button onClick={() => setDiscard(false)}>Keep editing</Button><Button variant="danger" onClick={onClose}>Discard changes</Button></div></div></div>}
      {error && <p className="error-box" role="alert">{error}</p>}
      {tab === 'evidence' && <>
        <section className="facts-block">
          <div className="block-head"><h3>Last opened</h3><Button variant="ghost" disabled={researchBusy || !!busy} busy={busy === 'research'} onClick={() => void run('research', () => onAction('research'))}>{researchBusy ? 'Researching…' : target.research_status === 'idle' ? 'Research' : 'Research again'}</Button></div>
          <dl className="facts">
            <div><dt>Date</dt><dd className={target.historical_date ? '' : 'blank'}>{target.historical_date ? date(target.historical_date) : 'Unknown'}</dd></div>
            {target.historical_date && <div><dt>How we know</dt><dd>{dateKind(target.historical_date_meaning, target.historical_date_precision)}</dd></div>}
            <div><dt>Research</dt><dd>{researchBusy ? 'Searching for past postings…' : target.research_summary || statusLabel(target.research_status)}</dd></div>
          </dl>
        </section>
        <section className="facts-block">
          <div className="block-head"><h3>Source</h3>{target.monitoring_status === 'monitoring' && <Button variant="ghost" busy={busy === 'check'} disabled={!!busy} onClick={() => void run('check', () => onAction('check'))}>Check now</Button>}</div>
          {proposed ? <>
            <dl className="facts">
              <div><dt>Page</dt><dd><ExternalLink url={proposed}>{proposed.replace(/^https?:\/\//, '')}</ExternalLink></dd></div>
              <div><dt>Status</dt><dd>{target.monitoring_status === 'monitoring' ? <><Status value="monitoring" />{target.source_health !== 'healthy' && <span className={['failed', 'unsupported'].includes(target.source_health) ? 'error-text' : 'muted'}>, {statusLabel(target.source_health).toLowerCase()}</span>}</> : target.monitoring_status === 'paused' ? <Status value="paused" /> : target.source_url ? 'Not approved yet' : 'Suggested by research'}</dd></div>
              <div><dt>Checks</dt><dd>Every {target.check_interval_hours} h</dd></div>
              {target.last_checked_at && <div><dt>Last check</dt><dd>{date(target.last_checked_at, timezone, true)}</dd></div>}
              {target.monitoring_status === 'monitoring' && target.next_check_at && <div><dt>Next check</dt><dd>{date(target.next_check_at, timezone, true)}</dd></div>}
            </dl>
            {target.monitoring_status !== 'monitoring' && <div className="approve">
              <p>Watching starts once you confirm this is the employer's current careers page. The first check records what is already posted, so only new openings alert you.</p>
              <CheckBox checked={includeExisting} onChange={setIncludeExisting} label="Also email me the matching jobs already posted" />
              <Button variant="primary" className="full-width" busy={busy === 'approve'} disabled={!!busy} onClick={() => void run('approve', () => onAction('approve', includeExisting))}>Approve source & start watching</Button>
            </div>}
          </> : <p className="blank-note">No careers page yet. Research suggests one, or add it under Settings. <button className="link-button" onClick={() => setTab('edit')}>Add a page</button></p>}
        </section>
        <section className="facts-block">
          <div className="block-head"><h3>Evidence</h3>{evidence.length > 0 && <span className="muted">{evidence.length}</span>}</div>
          {evidenceLoading ? <div className="inline-loading"><LoaderCircle size={16} className="spin" />Loading</div> : evidenceError ? <div className="error-box" role="alert">{evidenceError}<Button variant="ghost" onClick={() => setReload(n => n + 1)}>Try again</Button></div> : evidence.length === 0 ? <p className="blank-note">None yet. Research keeps each page it reads, the sentence that supports a date, and what kind of date it is.</p> : <div className="evidence-list">{evidence.map(item => <article className="evidence-item" key={item.id}>
            {item.excerpt && <blockquote>“{item.excerpt}”</blockquote>}
            <dl className="facts">
              {item.date_value && <div><dt>Date</dt><dd>{date(item.date_value)}{dateKind(item.date_meaning, item.date_precision) && <span className="muted">, {dateKind(item.date_meaning, item.date_precision).toLowerCase()}</span>}</dd></div>}
              <div><dt>Source</dt><dd><ExternalLink url={item.url} /></dd></div>
              <div><dt>Read</dt><dd>{date(item.retrieved_at, timezone, true)}</dd></div>
            </dl>
            {item.explanation && <p className="evidence-note">{item.explanation}</p>}
          </article>)}</div>}
          {target.reference_url && <dl className="facts reference"><div><dt>Your link</dt><dd><ExternalLink url={target.reference_url}>{target.reference_url.replace(/^https?:\/\//, '')}</ExternalLink></dd></div></dl>}
        </section>
      </>}
      {tab === 'edit' && <form onSubmit={e => {e.preventDefault(); void run('save', async () => {
        const {id: _id, version: _version, ...fields} = draft
        const patch: Partial<TargetInput> = {}
        type EditableKey = Exclude<keyof TargetInput, 'id' | 'version'>
        for (const key of Object.keys(fields) as EditableKey[]) {if (fields[key] !== target[key]) Object.assign(patch, {[key]: fields[key]})}
        if ('source_url' in patch || 'connector' in patch) patch.monitoring_status = 'draft'
        if (Object.keys(patch).length) await onPatch(patch)
        setDirty(false); setSaved(true)
      })}}>
        <TargetFields draft={draft} change={change} advanced />
        <div className="section-divider" /><h3 className="form-section-title">Last opened</h3><p className="form-description">A date you enter is marked as added by you. Keep it as precise as you actually know it.</p>
        <Field label="Date" hint={`For example ${nextCohortYear() - 2}-09-12, ${nextCohortYear() - 2}-09, or Sep–Oct ${nextCohortYear() - 2}. Blank means unknown.`}><Input value={draft.historical_date || ''} onChange={e => change({historical_date: e.target.value || null, historical_date_meaning: e.target.value ? 'user_supplied' : 'unknown'})} placeholder="Unknown" /></Field>
        <Field label="Precision"><Select value={draft.historical_date_precision || 'unknown'} onChange={e => change({historical_date_precision: e.target.value, historical_date_meaning: 'user_supplied'})}><option value="unknown">Unknown</option><option value="day">Exact day</option><option value="month">Month only</option><option value="range">Range</option></Select></Field>
        <div className="drawer-save"><span>{saved ? 'Saved' : dirty ? 'Unsaved changes' : ''}</span><Button type="submit" variant="primary" busy={busy === 'save'} disabled={!!busy || !dirty}>Save changes</Button></div>
        <div className="section-divider" /><div className="target-controls"><div><strong>{target.monitoring_status === 'monitoring' ? 'Watching' : 'Not watching'}</strong><p>{target.monitoring_status === 'monitoring' ? 'Pausing stops checks and reminders until you resume.' : proposed ? 'Starts checking the careers page above.' : 'Add a careers page to start watching.'}</p></div>{target.monitoring_status === 'monitoring' ? <Button disabled={!!busy} onClick={() => void run('pause', () => onPatch({monitoring_status: 'paused'}))}>Pause</Button> : <Button disabled={!!busy || !proposed} onClick={() => void run('approve', () => onAction('approve'))}>Start watching</Button>}</div>
        <div className="target-controls danger-controls"><div><strong>Remove this target</strong><p>Stops watching and deletes what research found.</p></div><Button variant="danger" onClick={() => setDeleting(!deleting)}>Remove</Button></div>
        {deleting && <div className="delete-confirm" role="alert"><div><strong>Remove {target.company}?</strong><p>Its research, evidence, and openings are deleted. This can't be undone.</p><Button onClick={() => setDeleting(false)}>Keep it</Button><Button variant="danger" busy={busy === 'delete'} disabled={!!busy} onClick={() => void run('delete', onDelete)}>Remove {target.company}</Button></div></div>}
      </form>}
      {tab === 'matches' && (matches.length ? <div className="evidence-list">{matches.map(match => <article className="evidence-item" key={match.id}><h3 className="item-title"><ExternalLink url={match.url}>{match.title}</ExternalLink></h3><dl className="facts"><div><dt>Status</dt><dd><Status value={match.status} />{match.closed && <span className="muted">, closed</span>}</dd></div><div><dt>Location</dt><dd>{match.location || 'Not stated'}</dd></div><div><dt>Found</dt><dd>{date(match.first_seen_at, timezone)}</dd></div></dl></article>)}</div> : <Empty title="No openings yet" description="Openings from the approved page appear here as checks find them." />)}
    </div>
  </Modal>
}
