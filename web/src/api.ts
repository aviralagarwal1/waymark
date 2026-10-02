export type TargetInput = {
  company: string; role: string; location: string; employment_type: string; level: string;
  start_period: string; watch_from: string | null; watch_until: string | null; notes: string;
  reference_url: string; source_url: string; connector: string; check_interval_hours: number;
  monitoring_status: 'draft' | 'monitoring' | 'paused';
  historical_date?: string | null; historical_date_precision?: string; historical_date_meaning?: string;
  id?: string; version?: number;
}
export type Target = TargetInput & {
  id: string; version: number; research_status: string; source_health: string;
  last_checked_at: string | null; next_check_at: string | null;
  historical_date: string | null; historical_date_precision: string; historical_date_meaning: string;
  research_summary: string; proposed_source_url: string; proposed_connector: string; created_at: string; source_error: string;
}
export type Evidence = {
  id: string; target_id: string; url: string; excerpt: string; retrieved_at: string; kind: string;
  date_value: string | null; date_precision: string; date_meaning: string; match_status: string; explanation: string;
}
export type Match = {
  id: string; target_id: string; company: string; title: string; url: string; location: string;
  status: 'new' | 'applied' | 'dismissed' | 'snoozed'; first_seen_at: string; published_at: string | null;
  date_meaning: string; reason: string; snoozed_until: string | null; closed: boolean; initial_notified_at: string | null;
}
export type Preferences = {
  timezone: string; check_interval_hours: number; email_mode: 'scan' | 'immediate' | 'daily' | 'weekly' | 'off';
  digest_hour: number; digest_weekday: number; reminder_days: number[]; quiet_start: number | null;
  quiet_end: number | null; daily_email_cap: number; default_role: string;
  default_location: string; default_start_period: string; default_employment_type: string; research_monthly_budget_usd: number;
}
export type Health = {
  status: string; mode: string; worker_last_seen: string | null;
  counts: {targets: number; monitoring: number; matches: number; pending_tasks: number};
  configuration: {ai: boolean; email: boolean; email_transport: 'preview' | 'smtp' | 'resend'}; source_errors: unknown[];
}
export type Task = {id: string; kind: string; status: string; target_id: string | null; error: string | null; created_at: string; updated_at: string}
export type Delivery = {id: string; subject: string; plain_body: string; status: string; created_at: string; sent_at: string | null; kind: string; recipient: string; error: string}
export type ImportPreview = {columns: string[]; rows: TargetInput[]; errors: {row: number; message: string}[]; existing_ids: string[]}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { ...(init?.body instanceof FormData ? {} : {'Content-Type': 'application/json'}), ...init?.headers },
  })
  // A lapsed session sends the reader to sign in, then back where they were.
  // Account actions report their own 401s (a wrong password) instead; asking
  // who is signed in is a workspace request like any other.
  if (res.status === 401 && (!path.startsWith('/auth/') || path === '/auth/me')) {
    window.location.href = `/signin?next=${encodeURIComponent(window.location.pathname)}`
    return new Promise<T>(() => {})
  }
  if (!res.ok) {
    let message = `Request failed (${res.status}).`
    try {
      const data = await res.json()
      message = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail)
        ? data.detail.map((item: {msg?: string; loc?: string[]}) => `${item.loc?.slice(1).join('.') || 'Input'}: ${item.msg}`).join('; ')
        : message
    } catch { /* preserve HTTP error */ }
    throw new Error(res.status === 409 ? 'This row changed while you were editing. We refreshed it; please review and try again.' : message)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}
export function write<T>(path: string, body: unknown, method = 'POST') { return api<T>(path, {method, body: JSON.stringify(body)}) }
export const messageOf = (e: unknown) => e instanceof Error ? e.message : 'Something went wrong. Please try again.'
export const safeUrl = (url: string | undefined | null) => { try { const u = new URL(url || ''); return ['http:', 'https:'].includes(u.protocol) ? u.href : undefined } catch { return undefined } }
export const words = (value: string | undefined | null) => (value || 'unknown').replaceAll('_', ' ')
// The app's vocabulary, defined once. Stored values are field names; these are
// what a person would say. Anything unmapped falls back to plain words.
const STATUS_LABELS: Record<string, string> = {
  monitoring: 'Watching', draft: 'Draft', paused: 'Paused',
  healthy: 'Healthy', failed: 'Failing', unsupported: 'Unsupported', unknown: 'Not checked',
  idle: 'Not researched', queued: 'Queued', researching: 'Researching', ready: 'Research ready', needs_review: 'Needs review',
  running: 'Running', done: 'Done', stale: 'Outdated', canceled: 'Canceled',
  pending: 'Queued', preview: 'Preview only', sent: 'Sent', uncertain: 'Uncertain', delivery_uncertain: 'Uncertain',
  new: 'New', applied: 'Applied', dismissed: 'Dismissed', snoozed: 'Snoozed',
}
export const statusLabel = (value: string) => STATUS_LABELS[value] || words(value).replace(/^\w/, c => c.toUpperCase())
const MEANINGS: Record<string, string> = {original_posted: 'posted', last_published: 'republished', updated: 'updated', archive_observed: 'seen in an archive', announced_expected: 'announced', user_supplied: 'added by you'}
const PRECISIONS: Record<string, string> = {day: 'exact day', month: 'month only', range: 'date range'}
// "Announced, month only": how a date was established, in a few words.
export function dateKind(meaning: string | undefined | null, precision?: string | null) {
  const parts = [MEANINGS[meaning || ''], PRECISIONS[precision || '']].filter(Boolean)
  const text = parts.join(', ')
  return text ? text[0].toUpperCase() + text.slice(1) : ''
}
// Example years roll forward with the clock so no hint or template goes stale
// (design, Time). Recruiting runs about a year ahead: this autumn hires for
// next year's cohort, and last cycle opened the autumn before.
export const nextCohortYear = () => new Date().getFullYear() + 1
export function importTemplateHref() {
  const start = nextCohortYear()
  const rows = ['company,role,location,employment_type,level,start_period,watch_from,watch_until,notes,reference_url,source_url,connector',
    `ExampleCo,Associate Product Manager,United States,FullTime,entry,Summer ${start},${start - 1}-08-01,${start - 1}-12-01,Optional notes,,,auto`]
  return `data:text/csv;charset=utf-8,${encodeURIComponent(rows.join('\n') + '\n')}`
}
export function date(value: string | null | undefined, timezone?: string, time = false) {
  if (!value) return 'Not yet'
  if (/^\d{4}-\d{2}$/.test(value)) return new Date(`${value}-01T12:00:00Z`).toLocaleDateString(undefined, {month: 'short', year: 'numeric', timeZone: 'UTC'})
  if (/^\d{4}$/.test(value)) return value
  const parsed = new Date(value.length === 10 ? `${value}T12:00:00Z` : value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric', ...(time ? {hour: 'numeric', minute: '2-digit'} : {}), timeZone: value.length === 10 ? 'UTC' : timezone})
}
// Logs read by day and time in the user's timezone: "Today", "Yesterday",
// then "Sep 30", with the year only when it isn't this year.
const dayKey = (value: Date, timezone: string) => value.toLocaleDateString('en-CA', {timeZone: timezone})
export function dayLabel(value: string, timezone: string) {
  const when = new Date(value), now = new Date()
  if (dayKey(when, timezone) === dayKey(now, timezone)) return 'Today'
  if (dayKey(when, timezone) === dayKey(new Date(now.getTime() - 86400000), timezone)) return 'Yesterday'
  const sameYear = when.toLocaleDateString('en-US', {year: 'numeric', timeZone: timezone}) === now.toLocaleDateString('en-US', {year: 'numeric', timeZone: timezone})
  return when.toLocaleDateString(undefined, {weekday: sameYear ? 'short' : undefined, month: 'short', day: 'numeric', year: sameYear ? undefined : 'numeric', timeZone: timezone})
}
export const clock = (value: string, timezone: string) => new Date(value).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit', timeZone: timezone})
// "just now", "4 min ago", "in 5 h": for times that matter relative to now.
export function relative(value: string, now = Date.now()) {
  const seconds = Math.round((new Date(value).getTime() - now) / 1000)
  const size = Math.abs(seconds)
  if (size < 45) return seconds > 0 ? 'in a moment' : 'just now'
  const [amount, unit] = size < 3600 ? [Math.round(size / 60), 'min'] : size < 172800 ? [Math.round(size / 3600), 'h'] : [Math.round(size / 86400), 'days']
  return seconds > 0 ? `in ${amount} ${unit}` : `${amount} ${unit} ago`
}
export function emptyTarget(p: Preferences): TargetInput {
  return {company: '', role: p.default_role, location: p.default_location, employment_type: p.default_employment_type,
    level: 'entry', start_period: p.default_start_period, watch_from: null, watch_until: null, notes: '', reference_url: '',
    source_url: '', connector: 'auto', check_interval_hours: p.check_interval_hours, monitoring_status: 'draft'}
}

export function editableTarget(target: Target): TargetInput {
  const {company, role, location, employment_type, level, start_period, watch_from, watch_until,
    notes, reference_url, source_url, connector, check_interval_hours, monitoring_status,
    historical_date, historical_date_precision, historical_date_meaning} = target
  return {company, role, location, employment_type, level, start_period, watch_from, watch_until,
    notes, reference_url, source_url, connector, check_interval_hours, monitoring_status,
    historical_date, historical_date_precision, historical_date_meaning}
}
