import { useRef, useState } from 'react'
import type { ImportPreview, Preferences, TargetInput } from './api'
import { api, emptyTarget, importTemplateHref, messageOf, nextCohortYear, write } from './api'
import { Button, CheckBox, Field, Input, Modal, Select } from './components'

const fields = [['company', 'Company'], ['role', 'Role / program'], ['location', 'Location'], ['start_period', 'Intended start'], ['employment_type', 'Employment type'], ['level', 'Experience level'], ['reference_url', 'Prior posting URL'], ['source_url', 'Current source URL'], ['connector', 'Connector'], ['watch_from', 'Watch from'], ['watch_until', 'Watch until'], ['check_interval_hours', 'Check interval (hours)'], ['notes', 'Notes'], ['historical_date', 'Historical date'], ['historical_date_precision', 'Date precision'], ['historical_date_meaning', 'Date meaning'], ['id', 'Existing row ID'], ['version', 'Row version']]
const csv = (value: string) => `"${value.replaceAll('"', '""')}"`
function pasteFile(text: string, p: Preferences) {
  const lines = text.trim().split(/\r?\n/).filter(line => line.trim())
  if (!lines.length) throw new Error('Paste at least one company or job URL.')
  const separator = lines[0].includes('\t') ? '\t' : ','
  const first = lines[0].split(separator).map(cell => cell.trim().toLowerCase().replaceAll('"', ''))
  const hasHeader = first.some(cell => ['company', 'employer', 'company name'].includes(cell))
  if (hasHeader) return new File([separator === '\t' ? lines.map(line => line.split('\t').map(csv).join(',')).join('\n') : text], 'pasted-targets.csv', {type: 'text/csv'})
  const defaults = emptyTarget(p)
  // The server needs a role on every row; say so here rather than let it reject the rows as unmapped columns.
  if (!defaults.role.trim() && lines.some(line => !(line.split('\t')[1] || '').trim())) throw new Error('Add a role for the rows that only name a company.')
  const rows = lines.map(line => {
    const parts = line.split('\t').map(cell => cell.trim())
    let company = parts[0]; let url = parts[4] || ''
    if (/^https?:\/\//i.test(company)) {
      url = company
      const host = new URL(company).hostname.replace(/^www\./, '')
      company = host.split('.')[0]
    }
    return [company, parts[1] || defaults.role, parts[2] || defaults.location, parts[3] || defaults.start_period, url, defaults.employment_type, String(defaults.check_interval_hours)].map(csv).join(',')
  })
  return new File([['company,role,location,start_period,reference_url,employment_type,check_interval_hours', ...rows].join('\n')], 'pasted-targets.csv', {type: 'text/csv'})
}

export default function ImportDialog({preferences, onClose, onImported}: {preferences: Preferences; onClose: () => void; onImported: (message: string) => Promise<void>}) {
  const [tab, setTab] = useState('paste')
  const [paste, setPaste] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [mappingOpen, setMappingOpen] = useState(false)
  const [merge, setMerge] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [defaultRole, setDefaultRole] = useState(preferences.default_role)
  const [mappingDirty, setMappingDirty] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const doPreview = async (selected?: File, remap = false) => {
    setBusy('preview'); setError('')
    try {
      const upload = selected || (tab === 'paste' ? pasteFile(paste, {...preferences, default_role: defaultRole}) : file)
      if (!upload) throw new Error('Choose a CSV or Excel workbook first.')
      setFile(upload)
      const body = new FormData(); body.append('file', upload)
      if (remap && Object.keys(mapping).length) body.append('mapping', JSON.stringify(mapping))
      const result = await api<ImportPreview>('/imports/preview', {method: 'POST', body})
      setPreview(result); setMappingDirty(false)
      if (!remap) setMapping(Object.fromEntries(fields.filter(([field]) => result.columns.includes(field)).map(([field]) => [field, field])))
      if (result.errors.length && !result.rows.length) setMappingOpen(true)
    } catch (e) {setError(messageOf(e))} finally {setBusy('')}
  }
  const updateRow = (index: number, patch: Partial<TargetInput>) => setPreview(p => p ? {...p, rows: p.rows.map((row, i) => i === index ? {...row, ...patch} : row)} : p)
  const invalidRows = preview?.rows.filter(row => !row.company.trim() || !row.role.trim()).length || 0
  const conflict = (row: TargetInput) => !!row.id && !!preview?.existing_ids.includes(row.id)
  return <Modal title="Import targets" onClose={onClose} wide>
    <div className="modal-body import-body">
      {!preview ? <><div className="tabs modal-tabs" role="tablist" aria-label="Import from"><button role="tab" aria-selected={tab === 'paste'} onClick={() => setTab('paste')}>Paste a list</button><button role="tab" aria-selected={tab === 'file'} onClick={() => setTab('file')}>Upload a spreadsheet</button></div>
        {tab === 'paste' ? <><Field label="Companies or job links" hint="One per line. Rows copied from a spreadsheet keep their columns: company, role, location, start, and a past posting link."><textarea className="input paste-area" rows={7} value={paste} onChange={e => setPaste(e.target.value)} placeholder={`Northstar Labs\nHarbor Robotics\nhttps://jobs.example.com/apm-${nextCohortYear() - 2}`} /></Field><Field label="Role for rows without one" hint="Your default location, start, and employment type fill in the rest. A link starts with the site's name as the company, so check it in the preview."><Input value={defaultRole} onChange={e => setDefaultRole(e.target.value)} placeholder="Software Engineer" /></Field></> : <><input ref={inputRef} className="sr-only" type="file" accept=".csv,.xlsx" aria-label="Choose a CSV or XLSX file" onChange={e => {const chosen = e.target.files?.[0]; if (chosen) {setFile(chosen); void doPreview(chosen)}}} /><button className="upload-zone" onClick={() => inputRef.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault(); const selected = e.dataTransfer.files[0]; if (selected) {setFile(selected); void doPreview(selected)}}}><strong>{file ? file.name : 'Drop a CSV or .xlsx file'}</strong><p>or choose one from your computer</p></button><p className="form-description">Columns are matched by name, and you can remap them before importing. A Waymark export imports back as updates. <a href={importTemplateHref()} download="waymark-template.csv">Download the template</a></p></>}
      </> : <><div className="import-file-summary"><div><strong>{tab === 'paste' ? 'Pasted list' : file?.name}</strong><small>{preview.rows.length} {preview.rows.length === 1 ? 'row' : 'rows'} ready{preview.errors.length ? `, ${preview.errors.length} skipped` : ''}</small></div><Button variant="ghost" onClick={() => {setPreview(null); setMapping({}); setError('')}}>Start over</Button></div>
        <button className="link-button mapping-toggle" aria-expanded={mappingOpen} onClick={() => setMappingOpen(!mappingOpen)}>{mappingOpen ? 'Hide columns' : 'Match columns'}</button>
        {mappingOpen && <div className="mapping-grid">{fields.map(([field, label]) => <Field key={field} label={label}><Select value={mapping[field] || ''} onChange={e => {setMappingDirty(true); setMapping(m => {const next = {...m}; if (e.target.value) next[field] = e.target.value; else delete next[field]; return next})}}><option value="">Not in this file</option>{preview.columns.map(column => <option key={column} value={column}>{column}</option>)}</Select></Field>)}<Button busy={busy === 'preview'} onClick={() => void doPreview(file || undefined, true)}>Apply and recheck</Button></div>}
        {mappingDirty && <p className="notice">Apply the new column matches before importing.</p>}
        {preview.errors.length > 0 && <div className="import-errors"><strong>{preview.errors.length === 1 ? 'One row is skipped' : `${preview.errors.length} rows are skipped`}</strong><ul>{preview.errors.slice(0, 20).map((error, index) => <li key={index}>Row {error.row}: {error.message}</li>)}</ul>{preview.errors.length > 20 && <small>And {preview.errors.length - 20} more.</small>}<p>Fix them in the file or the column matches to include them.</p></div>}
        {preview.rows.length > 0 && <><div className="import-preview-scroll"><table className="import-preview-table"><thead><tr><th>Company</th><th>Role</th><th>Location</th><th>Start</th><th>Import as</th></tr></thead><tbody>{preview.rows.map((row, i) => <tr key={i}><td><input aria-label={`Company for row ${i + 1}`} value={row.company} onChange={e => updateRow(i, {company: e.target.value})} required /></td><td><input aria-label={`Role for row ${i + 1}`} value={row.role} onChange={e => updateRow(i, {role: e.target.value})} required /></td><td>{row.location || '—'}</td><td>{row.start_period || '—'}</td><td className={conflict(row) && !merge ? 'error-text' : ''}>{conflict(row) ? (merge ? 'Update' : 'Already exists') : 'New'}</td></tr>)}</tbody></table></div><CheckBox checked={merge} onChange={setMerge} label="Update targets that already exist" /><p className="form-description">New targets start as drafts until you research them and approve a careers page.</p></>}
      </>}
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
    <div className="modal-footer"><span className="muted">{preview ? 'Nothing is saved until you import.' : 'Up to 5 MB or 5,000 rows.'}</span>{preview ? <Button variant="primary" busy={busy === 'commit'} disabled={!preview.rows.length || !!invalidRows || mappingDirty || !!busy} onClick={async () => {setBusy('commit'); setError(''); try {
      const result = await write<{created: number; updated: number; errors: {row?: number; message?: string}[]}>('/imports/commit', {rows: preview.rows, merge})
      await onImported(`Imported ${result.created} new targets${result.updated ? ` and updated ${result.updated}` : ''}.`)
      if (result.errors.length) {setError(`Some rows were not saved: ${result.errors.map(item => typeof item === 'string' ? item : item.message || JSON.stringify(item)).join('; ')}. The rest are in your watchlist; check them before trying again.`); setPreview(null)} else onClose()
    } catch (e) {setError(messageOf(e))} finally {setBusy('')}}}>Import {preview.rows.length} target{preview.rows.length === 1 ? '' : 's'}</Button> : <Button variant="primary" busy={busy === 'preview'} disabled={tab === 'paste' ? !paste.trim() : !file} onClick={() => void doPreview()}>Preview</Button>}</div>
  </Modal>
}
