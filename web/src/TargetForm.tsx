import { useState } from 'react'
import type { Preferences, TargetInput } from './api'
import { emptyTarget, messageOf, nextCohortYear } from './api'
import { Button, CheckBox, Field, Input, Modal, Select } from './components'

export const employmentOptions = <><option value="FullTime">Full-time</option><option value="Intern">Internship</option><option value="PartTime">Part-time</option><option value="Contract">Contract</option><option value="Temporary">Temporary</option></>
const connectorOptions = <><option value="auto">Detect automatically</option><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option><option value="ashby">Ashby</option><option value="jsonld">JobPosting page</option></>

export function TargetFields({draft, change, advanced = false}: {draft: TargetInput; change: (patch: Partial<TargetInput>) => void; advanced?: boolean}) {
  return <>
    <div className="form-grid"><Field label="Company"><Input required autoComplete="organization" value={draft.company} placeholder="Northstar Labs" onChange={e => change({company: e.target.value})} /></Field>
      <Field label="Role"><Input required value={draft.role} placeholder="Software Engineer, New Grad" onChange={e => change({role: e.target.value})} /></Field>
      <Field label="Location"><Input value={draft.location} placeholder="London or remote" onChange={e => change({location: e.target.value})} /></Field>
      <Field label="Start"><Input value={draft.start_period} placeholder={`Summer ${nextCohortYear()}`} onChange={e => change({start_period: e.target.value})} /></Field>
      <Field label="Employment type"><Select value={draft.employment_type} onChange={e => change({employment_type: e.target.value})}>{employmentOptions}</Select></Field>
      <Field label="Experience level"><Select value={draft.level} onChange={e => change({level: e.target.value})}><option value="entry">Entry level or new grad</option><option value="intern">Intern or student</option><option value="mid">Mid level</option><option value="senior">Senior</option><option value="any">Any level</option></Select></Field>
    </div>
    <Field label="Past posting" hint="Optional. An old posting tells research which program and cycle you mean."><Input type="url" value={draft.reference_url} placeholder={`https://jobs.example.com/apm-${nextCohortYear() - 2}`} onChange={e => change({reference_url: e.target.value})} /></Field>
    <div className="form-grid"><Field label="Watch from" hint="Checks start on this date."><Input type="date" value={draft.watch_from || ''} onChange={e => change({watch_from: e.target.value || null})} /></Field>
      <Field label="Watch until"><Input type="date" min={draft.watch_from || undefined} value={draft.watch_until || ''} onChange={e => change({watch_until: e.target.value || null})} /></Field></div>
    <Field label="Notes" hint="The program, cycle, or eligibility that matters. Research reads these."><textarea className="input" rows={3} value={draft.notes} onChange={e => change({notes: e.target.value})} /></Field>
    {advanced && <><div className="section-divider" /><h3 className="form-section-title">Careers page</h3>
      <Field label="Page to watch" hint="The board that lists current openings, not a single old posting."><Input type="url" value={draft.source_url} placeholder="https://boards.greenhouse.io/company" onChange={e => change({source_url: e.target.value})} /></Field>
      <div className="form-grid"><Field label="Board type"><Select value={draft.connector} onChange={e => change({connector: e.target.value})}>{connectorOptions}{draft.connector === 'demo' && <option value="demo">Demo source</option>}</Select></Field>
        <Field label="Check every (hours)"><Input type="number" min="0.25" max="8760" step="0.25" value={draft.check_interval_hours} onChange={e => change({check_interval_hours: Number(e.target.value)})} /></Field></div></>}
  </>
}

export function NewTarget({preferences, researchOn, onClose, onSave}: {preferences: Preferences; researchOn: boolean; onClose: () => void; onSave: (input: TargetInput, research: boolean) => Promise<void>}) {
  const [draft, setDraft] = useState(emptyTarget(preferences))
  const [research, setResearch] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // Without research, the careers page is the only way a target gets watched.
  const [advanced, setAdvanced] = useState(!researchOn)
  return <Modal title="Add target" onClose={onClose} wide>
    <form onSubmit={async e => {e.preventDefault(); setBusy(true); setError(''); try {await onSave(draft, research); onClose()} catch (err) {setError(messageOf(err))} finally {setBusy(false)}}}>
      <div className="modal-body"><TargetFields draft={draft} change={patch => setDraft(d => ({...d, ...patch}))} advanced={advanced} />
      <button type="button" className="link-button form-toggle" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>{advanced ? 'Leave the careers page to research' : 'I know the careers page'}</button>
      {error && <p className="error-box" role="alert">{error}</p>}</div>
      <div className="modal-footer"><CheckBox label={researchOn ? 'Research when it opened last year' : 'Check the careers page I added'} checked={research} onChange={setResearch} /><Button variant="primary" type="submit" busy={busy}>Add target</Button></div>
    </form>
  </Modal>
}
