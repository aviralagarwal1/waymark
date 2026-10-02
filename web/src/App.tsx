import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, BriefcaseBusiness, CircleHelp, ExternalLink as LinkIcon, LayoutList, LoaderCircle, LogOut, RefreshCw, Settings2, X } from 'lucide-react'
import type { Delivery, Health, Match, Preferences, Target, TargetInput, Task } from './api'
import { api, messageOf, write } from './api'
import { Button, Modal, SiteFooter, Wordmark } from './components'
import { brand } from './brand'
import { NewTarget } from './TargetForm'
import Watchlist from './Watchlist'
import TargetDrawer from './TargetDrawer'
import ImportDialog from './ImportDialog'
import Matches from './Matches'
import Settings from './Settings'
import ActivityPage from './Activity'

type Page = 'watchlist' | 'matches' | 'activity' | 'settings'
const pageNames: Record<Page, string> = {watchlist: 'Watchlist', matches: 'Openings', activity: 'Activity', settings: 'Preferences'}
type Snapshot = {targets: Target[]; matches: Match[]; tasks: Task[]; deliveries: Delivery[]; preferences: Preferences; health: Health}

export default function App() {
  const [page, setPage] = useState<Page>('watchlist')
  const [data, setData] = useState<Snapshot | null>(null)
  const dataRef = useRef<Snapshot | null>(null)
  const [loadError, setLoadError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [loading, setLoading] = useState(true)
  const [newTarget, setNewTarget] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [help, setHelp] = useState(false)
  const [drawerId, setDrawerId] = useState<string | null>(null)
  const [toast, setToast] = useState<{message: string; error: boolean} | null>(null)
  const [reset, setReset] = useState(false)
  const [resetBusy, setResetBusy] = useState(false)
  const [account, setAccount] = useState('')
  useEffect(() => {void api<{email: string}>('/auth/me').then(me => setAccount(me.email))}, [])
  const signOut = async () => {await api('/auth/logout', {method: 'POST'}); window.location.href = '/'}
  const pending = useRef(new Map<string, number>())
  const queues = useRef(new Map<string, Promise<unknown>>())
  const lastVersions = useRef(new Map<string, number>())
  const polling = useRef(false)
  const mounted = useRef(true)

  const updateData = useCallback((fn: (d: Snapshot) => Snapshot) => {
    setData(d => {if (!d) return d; const next = fn(d); dataRef.current = next; return next})
  }, [])
  const notify = useCallback((message: string, error = false) => setToast({message, error}), [])
  useEffect(() => {if (!toast) return; const id = window.setTimeout(() => setToast(null), toast.error ? 10000 : 4500); return () => window.clearTimeout(id)}, [toast])

  const refresh = useCallback(async () => {
    if (polling.current) return
    polling.current = true
    try {
      const [targets, matches, tasks, deliveries, preferences, health] = await Promise.all([
        api<Target[]>('/targets'), api<Match[]>('/matches'), api<Task[]>('/tasks'), api<Delivery[]>('/deliveries'), api<Preferences>('/settings'), api<Health>('/health'),
      ])
      if (!mounted.current) return
      targets.forEach(t => {if (!pending.current.has(t.id)) lastVersions.current.set(t.id, t.version)})
      setData(current => {
        const next = {targets: targets.map(t => pending.current.has(t.id) ? current?.targets.find(old => old.id === t.id) || t : t), matches, tasks, deliveries, preferences, health}
        dataRef.current = next; return next
      })
      setLoadError(''); setConnectionError('')
    } catch (error) {
      if (!mounted.current) return
      if (dataRef.current) setConnectionError(messageOf(error)); else setLoadError(messageOf(error))
    } finally {polling.current = false; if (mounted.current) setLoading(false)}
  }, [])
  useEffect(() => {
    mounted.current = true
    void refresh()
    const timer = window.setInterval(() => {if (document.visibilityState === 'visible') void refresh()}, 7000)
    const focus = () => void refresh()
    window.addEventListener('focus', focus)
    return () => {mounted.current = false; window.clearInterval(timer); window.removeEventListener('focus', focus)}
  }, [refresh])

  const patchTarget = useCallback(async (id: string, patch: Partial<TargetInput>) => {
    pending.current.set(id, (pending.current.get(id) || 0) + 1)
    updateData(d => ({...d, targets: d.targets.map(t => t.id === id ? {...t, ...patch} : t)}))
    const previous = queues.current.get(id) || Promise.resolve()
    const operation = previous.catch(() => undefined).then(async () => {
      const target = dataRef.current?.targets.find(t => t.id === id)
      if (!target) throw new Error('This target no longer exists.')
      const saved = await write<Target>(`/targets/${id}`, {...patch, version: lastVersions.current.get(id) ?? target.version}, 'PATCH')
      lastVersions.current.set(id, saved.version)
      updateData(d => ({...d, targets: d.targets.map(t => t.id === id ? (pending.current.get(id) === 1 ? saved : {...t, version: saved.version}) : t)}))
      return saved
    })
    queues.current.set(id, operation)
    try {await operation} catch (error) {notify(messageOf(error), true); throw error} finally {
      const remaining = (pending.current.get(id) || 1) - 1
      if (remaining) pending.current.set(id, remaining)
      else {pending.current.delete(id); queues.current.delete(id); void refresh()}
    }
  }, [notify, refresh, updateData])

  const act = useCallback(async (id: string, action: 'research' | 'approve' | 'check', includeExisting = false) => {
    await write(`/targets/${id}/${action}`, action === 'approve' ? {include_existing: includeExisting} : {})
    notify(action === 'research' ? 'Research queued. You can keep working while we look.' : action === 'approve' ? 'Source approved. Monitoring is ready to begin.' : 'Source check queued.')
    await refresh()
  }, [notify, refresh])
  const safeAct = async (id: string, action: 'research' | 'approve' | 'check') => {try {await act(id, action)} catch (e) {notify(messageOf(e), true)}}
  const saveMatch = async (match: Match, status: Match['status'], snoozedUntil?: string) => {
    try {
      const saved = await write<Match>(`/matches/${match.id}`, {status, ...(snoozedUntil ? {snoozed_until: snoozedUntil} : {})}, 'PATCH')
      updateData(d => ({...d, matches: d.matches.map(m => m.id === match.id ? saved : m)}))
      notify(status === 'applied' ? 'Marked applied. No more reminders for it.' : status === 'dismissed' ? 'Dismissed. No more reminders for it.' : status === 'snoozed' ? 'Reminders snoozed.' : 'Moved back to new.')
    } catch (error) {notify(messageOf(error), true); throw error}
  }
  const newCount = data?.matches.filter(m => m.status === 'new' && !m.closed).length || 0
  const workerAlive = data?.health.status === 'ok'
  const selected = data?.targets.find(t => t.id === drawerId)
  const demo = data?.health.mode === 'demo'

  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => setPage('watchlist')} aria-label={`${brand.name} home`}><Wordmark name={brand.name} /></button>
      <nav aria-label="Main navigation">{([
        ['watchlist', LayoutList], ['matches', BriefcaseBusiness], ['activity', Activity], ['settings', Settings2],
      ] as const).map(([key, Icon]) => <button key={key} className={`nav-item ${page === key ? 'active' : ''}`} onClick={() => setPage(key)} aria-current={page === key ? 'page' : undefined}><Icon size={19} /><span>{pageNames[key]}</span>{key === 'matches' && newCount > 0 && <span className="nav-count">{newCount}</span>}</button>)}</nav>
      <div className="sidebar-bottom">
        <button className="sidebar-help" onClick={() => setHelp(true)}><CircleHelp size={16} />How it works</button>
        <div className="account-row"><span className="account-email" title={account}>{account}</span><button className="sidebar-help" onClick={() => void signOut()}><LogOut size={16} />Sign out</button></div>
      </div>
    </aside>
    <div className="main-shell">{data && !workerAlive && <p className="offline-strip" role="status">Worker offline. Research, checks, and email are waiting.</p>}<header className="topbar"><div className="topbar-right">{data && !workerAlive && <span className="worker-status" title="Research, checks, and email wait until the worker runs.">Worker offline</span>}<button className="topbar-help" onClick={() => setHelp(true)} aria-label="How it works"><CircleHelp size={18} /></button>{demo && <button className="demo-label" onClick={() => setReset(true)}>Reset demo</button>}</div></header>
      <main id="main-content">
        {connectionError && <div className="connection-banner" role="alert">Connection interrupted. Showing your last saved data. <Button variant="ghost" onClick={() => void refresh()}>Retry<RefreshCw size={13} /></Button></div>}
        {loading ? <div className="initial-state"><LoaderCircle className="spin" size={28} /><h2>Opening your workspace…</h2></div> : loadError ? <div className="initial-state"><h2>We couldn’t reach your workspace.</h2><p>{loadError}</p><Button variant="primary" onClick={() => {setLoading(true); void refresh()}}>Try again<RefreshCw size={16} /></Button><small>Check your connection, then try again.</small></div> : data && <>
          {page === 'watchlist' && <Watchlist targets={data.targets} health={data.health} timezone={data.preferences.timezone} matches={data.matches} onNew={() => setNewTarget(true)} onImport={() => setShowImport(true)} onOpen={setDrawerId} onPatch={patchTarget} onAction={safeAct} onShowMatches={() => setPage('matches')} onBatchAction={async (ids, action) => {let ok = 0; const failures: string[] = []; for (const id of ids) {try {await write(`/targets/${id}/${action}`, {}); ok++} catch (e) {failures.push(messageOf(e))}} await refresh(); notify(`${ok} target${ok === 1 ? '' : 's'} ${action === 'research' ? 'queued for research' : action === 'approve' ? 'approved for monitoring' : 'queued for checking'}.${failures.length ? ` ${failures.length} failed: ${failures[0]}` : ''}`, failures.length > 0)}} />}
          {page === 'matches' && <Matches matches={data.matches} timezone={data.preferences.timezone} onSave={saveMatch} onOpenTarget={id => setDrawerId(id)} />}
          {page === 'activity' && <ActivityPage tasks={data.tasks} deliveries={data.deliveries} targets={data.targets} health={data.health} timezone={data.preferences.timezone} emailCap={data.preferences.daily_email_cap} onOpenTarget={setDrawerId} onCheck={id => safeAct(id, 'check')} onTest={async () => {const result = await write<{status: string}>('/email/test', {}); notify(result.status === 'pending' ? 'Test email queued. The worker will process it.' : `Test email: ${result.status}.`); await refresh()}} />}
          {page === 'settings' && <Settings preferences={data.preferences} health={data.health} account={account} onSignOut={() => void signOut()} onDeleteAccount={async password => {await write('/auth/delete', {password}); window.location.href = '/'}} onSave={async preferences => {const saved = await write<Preferences>('/settings', preferences, 'PUT'); updateData(d => ({...d, preferences: saved})); notify('Preferences saved. Your schedule is up to date.')}} onTest={async () => {const result = await write<{status: string}>('/email/test', {}); notify(`Test email ${result.status === 'pending' ? 'queued' : result.status}. See Activity for delivery status.`); await refresh()}} />}
        </>}
      </main><SiteFooter />
    </div>
    {newTarget && data && <NewTarget preferences={data.preferences} researchOn={data.health.mode === 'demo' || data.health.configuration.ai} onClose={() => setNewTarget(false)} onSave={async (input, research) => {
      const saved = await write<Target>('/targets', input)
      updateData(d => ({...d, targets: [...d.targets, saved]})); lastVersions.current.set(saved.id, saved.version)
      if (research) {try {await write(`/targets/${saved.id}/research`, {})} catch (e) {notify(`Target saved; research could not start: ${messageOf(e)}`, true); await refresh(); return}}
      notify(research ? 'Target added. Research is queued.' : 'Target added to your watchlist.'); await refresh()
    }} />}
    {showImport && data && <ImportDialog preferences={data.preferences} onClose={() => setShowImport(false)} onImported={async text => {notify(text); await refresh()}} />}
    {selected && data && <TargetDrawer key={selected.id} target={selected} matches={data.matches.filter(m => m.target_id === selected.id)} timezone={data.preferences.timezone} onClose={() => setDrawerId(null)} onPatch={patch => patchTarget(selected.id, patch)} onAction={(action, initial) => act(selected.id, action, initial)} onDelete={async () => {await api(`/targets/${selected.id}`, {method: 'DELETE'}); setDrawerId(null); notify('Target removed from your workspace.'); await refresh()}} />}
    {help && <Modal title={`How ${brand.name} works`} onClose={() => setHelp(false)}><div className="modal-body"><ol className="guide">{[
      ['Add the roles you want', 'A company, the role, where, and when you want to start. Import a spreadsheet for a long list.'],
      ['Research when they opened', 'Research finds last cycle’s posting and quotes the page behind each date. A date no page supports stays unknown.'],
      ['Approve the careers page', 'Watching starts when you confirm the page. The first check records what is already posted, so only new openings alert you.'],
      ['Hear when one opens', 'Email on the schedule you set, then reminders until you mark it applied or dismiss it.'],
    ].map(([title, description]) => <li key={title}><h3>{title}</h3><p>{description}</p></li>)}</ol></div><div className="modal-footer"><span /><Button variant="primary" onClick={() => setHelp(false)}>Done</Button></div></Modal>}
    {reset && <Modal title="Reset the demo workspace?" subtitle="Restore the synthetic example targets, evidence, and settings." onClose={() => setReset(false)}><div className="modal-body"><p>This removes edits and targets in this demo workspace. Download an export first if you want to keep your changes.</p><a className="external-link" href="/api/exports/targets?format=xlsx" download>Download current watchlist<LinkIcon size={14} /></a></div><div className="modal-footer"><Button onClick={() => setReset(false)}>Keep my changes</Button><Button variant="danger" busy={resetBusy} onClick={async () => {setResetBusy(true); try {await write('/demo/reset', {}); setReset(false); setDrawerId(null); await refresh(); notify('Demo workspace restored.')} catch (e) {notify(messageOf(e), true)} finally {setResetBusy(false)}}}>Reset demo</Button></div></Modal>}
    {toast && <div className={`toast ${toast.error ? 'toast-error' : ''}`} role={toast.error ? 'alert' : 'status'}><span>{toast.message}</span><button onClick={() => setToast(null)} aria-label="Dismiss notification"><X size={17} /></button></div>}
  </div>
}
