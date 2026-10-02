import { useMemo, useState } from 'react'
import { flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable } from '@tanstack/react-table'
import type { ColumnDef, RowSelectionState, SortingState } from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ChevronDown, Plus, Upload } from 'lucide-react'
import type { Health, Match, Target, TargetInput } from './api'
import { date, dateKind, statusLabel } from './api'
import { Button, Editable, Empty, ExternalLink, SearchBox, Status } from './components'

type Props = {targets: Target[]; matches: Match[]; health: Health; timezone: string; onNew: () => void; onImport: () => void; onOpen: (id: string) => void; onPatch: (id: string, patch: Partial<TargetInput>) => Promise<void>; onAction: (id: string, action: 'research' | 'approve' | 'check') => Promise<void>; onBatchAction: (ids: string[], action: 'research' | 'approve' | 'check') => Promise<void>; onShowMatches: () => void}
type View = 'all' | 'monitoring' | 'review' | 'draft' | 'paused'

const needsReview = (t: Target) => ['ready', 'needs_review'].includes(t.research_status) && t.monitoring_status !== 'monitoring'
const researching = (t: Target) => ['queued', 'researching'].includes(t.research_status)

// One line under the state: what happens next, or what is wrong.
function stateNote(t: Target) {
  if (t.monitoring_status === 'monitoring') {
    if (t.source_health === 'failed' || t.source_health === 'unsupported') return {text: `Source ${statusLabel(t.source_health).toLowerCase()}`, error: true}
    return {text: `Checks every ${t.check_interval_hours} h`, error: false}
  }
  if (researching(t)) return {text: 'Researching…', error: false}
  if (t.research_status === 'failed') return {text: 'Research failed', error: true}
  if (needsReview(t)) return {text: 'Research ready to review', error: false}
  return {text: t.research_status === 'idle' ? 'Not researched' : statusLabel(t.research_status), error: false}
}

export default function Watchlist({targets, matches, timezone, onNew, onImport, onOpen, onPatch, onAction, onBatchAction, onShowMatches}: Props) {
  const [search, setSearch] = useState('')
  const [view, setView] = useState<View>('all')
  const [sorting, setSorting] = useState<SortingState>([])
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [advanced, setAdvanced] = useState(false)
  const [batchBusy, setBatchBusy] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const counts = {
    all: targets.length,
    monitoring: targets.filter(t => t.monitoring_status === 'monitoring').length,
    review: targets.filter(needsReview).length,
    draft: targets.filter(t => t.monitoring_status === 'draft').length,
    paused: targets.filter(t => t.monitoring_status === 'paused').length,
  }
  const newMatches = matches.filter(m => m.status === 'new' && !m.closed).length
  const visible = useMemo(() => targets.filter(t => view === 'all' || (view === 'review' ? needsReview(t) : t.monitoring_status === view)), [targets, view])
  const show = (next: View) => {setView(next); setSelection({})}
  const columns = useMemo<ColumnDef<Target>[]>(() => [
    {id: 'select', header: ({table}) => <input className="table-checkbox" type="checkbox" aria-label="Select all visible targets" checked={table.getIsAllRowsSelected()} onChange={table.getToggleAllRowsSelectedHandler()} />, cell: ({row}) => <input className="table-checkbox" type="checkbox" aria-label={`Select ${row.original.company}`} checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} />, size: 44, enableSorting: false},
    {accessorKey: 'company', header: 'Company', cell: ({row}) => <div className="company-cell"><Editable value={row.original.company} label={`Company for ${row.original.company}`} onSave={value => onPatch(row.original.id, {company: value})} /><Editable value={row.original.role} label={`Role at ${row.original.company}`} onSave={value => onPatch(row.original.id, {role: value})} placeholder="Add a role" /></div>, size: 300},
    {accessorKey: 'location', header: 'Location', cell: ({row}) => <Editable value={row.original.location} label={`Location for ${row.original.company}`} onSave={value => onPatch(row.original.id, {location: value})} placeholder="Anywhere" />, size: 160},
    {accessorKey: 'start_period', header: 'Start', cell: ({row}) => <Editable value={row.original.start_period} label={`Intended start at ${row.original.company}`} onSave={value => onPatch(row.original.id, {start_period: value})} placeholder="Add a start" />, size: 160},
    {accessorKey: 'historical_date', header: 'Last opened', cell: ({row}) => row.original.historical_date
      ? <button className="date-cell" onClick={() => onOpen(row.original.id)}><span>{date(row.original.historical_date)}</span><small>{dateKind(row.original.historical_date_meaning)}</small></button>
      : <span className="blank" aria-label="Unknown">—</span>, size: 150},
    {accessorKey: 'monitoring_status', header: 'Status', cell: ({row}) => {const note = stateNote(row.original); return <div className="state-cell"><Status value={row.original.monitoring_status} /><small className={note.error ? 'error-text' : ''}>{note.text}</small></div>}, size: 190},
    {id: 'research', header: 'Research', accessorFn: t => t.research_status, cell: ({row}) => <Status value={row.original.research_status} />, size: 150},
    {id: 'watch', header: 'Watch period', accessorFn: t => t.watch_from || '', cell: ({row}) => <span>{row.original.watch_from ? date(row.original.watch_from) : 'Anytime'}{row.original.watch_until && <small className="cell-subtext">Until {date(row.original.watch_until)}</small>}</span>, size: 150},
    {accessorKey: 'source_url', header: 'Source', cell: ({row}) => <ExternalLink url={row.original.source_url} />, size: 200},
    {accessorKey: 'reference_url', header: 'Past posting', cell: ({row}) => <ExternalLink url={row.original.reference_url} />, size: 200},
    {accessorKey: 'last_checked_at', header: 'Last check', cell: ({row}) => <span className="cell-date">{date(row.original.last_checked_at, timezone, true)}</span>, size: 170},
    {accessorKey: 'next_check_at', header: 'Next check', cell: ({row}) => <span className="cell-date">{date(row.original.next_check_at, timezone, true)}</span>, size: 170},
    {accessorKey: 'notes', header: 'Notes', cell: ({row}) => <Editable value={row.original.notes} label={`Notes for ${row.original.company}`} onSave={value => onPatch(row.original.id, {notes: value})} />, size: 250},
    // One next step per row, in words. Opening the row is always available.
    {id: 'actions', header: '', cell: ({row}) => {
      const t = row.original
      const canResearch = t.monitoring_status !== 'monitoring' && !researching(t) && !t.proposed_source_url && !t.source_url
      return <div className="row-actions">
        {canResearch && <button className="row-step" onClick={() => void onAction(t.id, 'research')} aria-label={`Research ${t.company}`}>Research</button>}
        <button className={`row-step ${needsReview(t) ? '' : 'quiet'}`} onClick={() => onOpen(t.id)} aria-label={`Open ${t.company} details`}>{needsReview(t) ? 'Review' : 'Open'}</button>
      </div>
    }, size: 96, enableSorting: false},
  ], [onOpen, onPatch, onAction, timezone])
  const table = useReactTable({data: visible, columns, state: {sorting, rowSelection: selection, globalFilter: search, columnVisibility: {research: advanced, watch: advanced, source_url: advanced, reference_url: advanced, last_checked_at: advanced, next_check_at: advanced, notes: advanced}}, getRowId: row => row.id, onSortingChange: setSorting, onRowSelectionChange: setSelection, onGlobalFilterChange: setSearch, getCoreRowModel: getCoreRowModel(), getFilteredRowModel: getFilteredRowModel(), getSortedRowModel: getSortedRowModel(), enableRowSelection: true, globalFilterFn: (row, _column, query) => `${row.original.company} ${row.original.role} ${row.original.location} ${row.original.notes} ${row.original.start_period}`.toLowerCase().includes(String(query).toLowerCase())})
  const selectedRows = table.getFilteredSelectedRowModel().rows
  const batch = async (action: 'research' | 'approve' | 'check') => {setBatchBusy(true); try {await onBatchAction(selectedRows.map(r => r.id), action); setSelection({})} finally {setBatchBusy(false)}}
  const tabs: [View, string][] = [['all', 'All'], ['monitoring', 'Watching'], ['review', 'To review'], ['draft', 'Drafts'], ['paused', 'Paused']]
  return <>
    <header className="page-head"><h1>Watchlist</h1><div className="page-actions"><Button onClick={onImport}><Upload size={15} />Import</Button><Button variant="primary" onClick={onNew}><Plus size={16} />Add target</Button></div></header>
    {targets.length > 0 && <dl className="summary" aria-label="Watchlist summary">
      <div><dt>Targets</dt><dd><button onClick={() => show('all')}>{counts.all}</button></dd></div>
      <div><dt>Watching</dt><dd><button onClick={() => show('monitoring')}>{counts.monitoring}</button></dd></div>
      <div><dt>To review</dt><dd><button onClick={() => show('review')}>{counts.review}</button></dd></div>
      <div><dt>New openings</dt><dd><button className={newMatches ? 'now' : ''} onClick={onShowMatches}>{newMatches}</button></dd></div>
    </dl>}
    {targets.length === 0 ? <Empty title="Add your first target" description="A company and the role you want there. Paste a whole list if you have one." action={<div className="button-group"><Button onClick={onImport}><Upload size={15} />Import a list</Button><Button variant="primary" onClick={onNew}><Plus size={15} />Add a target</Button></div>} /> : <section className="sheet">
      <div className="sheet-bar">
        <div className="tabs" role="tablist" aria-label="Filter watchlist">{tabs.map(([value, label]) => <button key={value} role="tab" aria-selected={view === value} onClick={() => show(value)}>{label}<span>{counts[value]}</span></button>)}</div>
        <div className="sheet-tools"><SearchBox value={search} onChange={setSearch} placeholder="Search" /><button className={`text-tool ${advanced ? 'active-tool' : ''}`} onClick={() => setAdvanced(!advanced)} aria-pressed={advanced}>{advanced ? 'Fewer columns' : 'Columns'}</button><div className="export-control"><button className="text-tool" aria-expanded={exportOpen} onClick={() => setExportOpen(!exportOpen)}>Export<ChevronDown size={13} /></button>{exportOpen && <div className="export-menu"><a href="/api/exports/targets?format=xlsx" download onClick={() => setExportOpen(false)}>Excel (.xlsx)<small>Targets and evidence</small></a><a href="/api/exports/targets?format=csv" download onClick={() => setExportOpen(false)}>CSV<small>Targets only</small></a></div>}</div></div>
      </div>
      {selectedRows.length > 0 && <div className="bulk-bar"><span>{selectedRows.length} selected</span><Button variant="ghost" busy={batchBusy} onClick={() => void batch('research')}>Research</Button><Button variant="ghost" busy={batchBusy} onClick={() => void batch('approve')}>Approve sources</Button><Button variant="ghost" busy={batchBusy} onClick={() => void batch('check')}>Check now</Button><button className="text-tool push-right" onClick={() => setSelection({})}>Clear</button></div>}
      {table.getRowModel().rows.length === 0 ? <Empty title="Nothing here" description={search ? 'No target matches that search.' : 'No targets in this view.'} action={<Button onClick={() => {setSearch(''); show('all')}}>Show all targets</Button>} /> : <div className="table-scroll"><table className="watchlist-table" style={{minWidth: advanced ? table.getTotalSize() : 960}}><thead>{table.getHeaderGroups().map(group => <tr key={group.id}>{group.headers.map(header => <th key={header.id} style={{width: header.getSize()}} aria-sort={header.column.getIsSorted() === 'asc' ? 'ascending' : header.column.getIsSorted() === 'desc' ? 'descending' : undefined}>{header.column.getCanSort() ? <button className="table-sort" onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header, header.getContext())}{header.column.getIsSorted() === 'asc' ? <ArrowUp size={12} /> : header.column.getIsSorted() === 'desc' ? <ArrowDown size={12} /> : null}</button> : flexRender(header.column.columnDef.header, header.getContext())}</th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map(row => <tr key={row.id} className={row.getIsSelected() ? 'row-selected' : ''}>{row.getVisibleCells().map(cell => <td key={cell.id} data-col={cell.column.id} data-label={typeof cell.column.columnDef.header === 'string' ? cell.column.columnDef.header : undefined}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody></table></div>}
      <div className="sheet-foot">{table.getRowModel().rows.length === targets.length ? `${targets.length} target${targets.length === 1 ? '' : 's'}` : `${table.getRowModel().rows.length} of ${targets.length} targets`}</div>
    </section>}
  </>
}
