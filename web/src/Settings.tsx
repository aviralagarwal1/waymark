import { useState } from 'react'
import type { Health, Preferences } from './api'
import { messageOf, nextCohortYear } from './api'
import { Button, Field, Input, Modal, Select } from './components'
import { employmentOptions } from './TargetForm'

const hours = Array.from({length: 24}, (_, i) => i)
const hourLabel = (n: number) => `${n % 12 || 12}:00 ${n < 12 ? 'AM' : 'PM'}`
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const timezones = ['America/Chicago', 'America/New_York', 'America/Los_Angeles', 'America/Denver', 'America/Toronto', 'America/Sao_Paulo', 'Europe/London', 'Europe/Berlin', 'Europe/Paris', 'Asia/Kolkata', 'Asia/Singapore', 'Asia/Tokyo', 'Australia/Sydney', 'Pacific/Auckland', 'UTC']

export default function Settings({preferences, health, account, onSave, onTest, onSignOut, onDeleteAccount}: {preferences: Preferences; health: Health; account: string; onSave: (p: Preferences) => Promise<void>; onTest: () => Promise<void>; onSignOut: () => void; onDeleteAccount: (password: string) => Promise<void>}) {
  const [draft, setDraft] = useState<Preferences>({...preferences})
  const [reminders, setReminders] = useState(preferences.reminder_days.join(', '))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [testMessage, setTestMessage] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [password, setPassword] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const closeDelete = () => {setDeleting(false); setPassword(''); setDeleteError('')}
  const change = (patch: Partial<Preferences>) => {setDraft(d => ({...d, ...patch})); setSaved(false)}
  const emailText = draft.email_mode === 'off' ? 'Off' : draft.email_mode === 'immediate' ? 'As matches arrive' : draft.email_mode === 'scan' ? 'After each scan' : draft.email_mode === 'daily' ? `Daily at ${hourLabel(draft.digest_hour)}` : `${weekdays[draft.digest_weekday]}s at ${hourLabel(draft.digest_hour)}`
  const reminderDays = reminders.split(',').map(d => d.trim()).filter(Boolean)
  const reminderText = reminderDays.length ? `${new Intl.ListFormat('en', {type: 'conjunction'}).format(reminderDays)} days after an alert` : 'None'
  const hoursText = (n: number) => n === 1 ? 'Every hour' : `Every ${n} hours`
  return <>
    <header className="page-head"><h1>Preferences</h1></header>
    <form className="settings-layout" onSubmit={async e => {
      e.preventDefault(); setError(''); setBusy('save')
      try {
        try {new Intl.DateTimeFormat('en', {timeZone: draft.timezone}).format()} catch {throw new Error('Enter a valid timezone, such as America/Chicago or Europe/London.')}
        const days = reminders.trim() ? reminders.split(',').map(s => Number(s.trim())) : []
        if (days.length > 12) throw new Error('Use at most 12 reminder offsets.')
        if (days.some(n => !Number.isInteger(n) || n < 1 || n > 365)) throw new Error('Reminder offsets must be whole days from 1 to 365, separated by commas.')
        if ((draft.quiet_start === null) !== (draft.quiet_end === null)) throw new Error('Set both quiet-hour times, or turn both off.')
        if (draft.quiet_start !== null && draft.quiet_start === draft.quiet_end) throw new Error('Quiet hours must have different start and end times.')
        const next = {...draft, reminder_days: [...new Set(days)].sort((a, b) => a - b)}
        await onSave(next); setDraft(next); setReminders(next.reminder_days.join(', ')); setSaved(true)
      } catch (err) {setError(messageOf(err))} finally {setBusy('')}
    }}>
      <div className="settings-main sheet">
        <section className="settings-section"><header><h2>Defaults</h2><p>New targets start with these. Each target can change them.</p></header>
          <div className="settings-fields"><div className="form-grid"><Field label="Role"><Input value={draft.default_role} onChange={e => change({default_role: e.target.value})} placeholder="Software Engineer" /></Field><Field label="Location"><Input value={draft.default_location} onChange={e => change({default_location: e.target.value})} placeholder="London or remote" /></Field><Field label="Start"><Input value={draft.default_start_period} onChange={e => change({default_start_period: e.target.value})} placeholder={`Summer ${nextCohortYear()}`} /></Field><Field label="Employment type"><Select value={draft.default_employment_type} onChange={e => change({default_employment_type: e.target.value})}>{employmentOptions}</Select></Field></div></div>
        </section>
        <section className="settings-section"><header><h2>Checks</h2><p>How often careers pages are checked, and the clock your emails follow.</p></header>
          <div className="settings-fields"><div className="form-grid"><Field label="Check every (hours)" hint="For new targets. Existing ones keep their own."><Input required type="number" min="0.25" max="8760" step="0.25" value={draft.check_interval_hours} onChange={e => change({check_interval_hours: Number(e.target.value)})} /></Field><Field label="Timezone"><Input required list="timezones" value={draft.timezone} onChange={e => change({timezone: e.target.value})} /><datalist id="timezones">{timezones.map(t => <option key={t} value={t} />)}</datalist></Field></div></div>
        </section>
        <section className="settings-section"><header><h2>Email</h2><p>When alerts reach your inbox. They go to the email on your account.</p></header>
          <div className="settings-fields"><div className="choices" role="radiogroup" aria-label="Email schedule">{([
            ['scan', 'After each scan', 'One summary when a check finds new openings'], ['immediate', 'As matches arrive', 'A separate email for each opening'], ['daily', 'Daily digest', 'New openings in one email a day'], ['weekly', 'Weekly digest', 'New openings in one email a week'], ['off', 'Off', 'Openings stay in the app'],
          ] as const).map(([value, label, help]) => <label key={value} className={`choice ${draft.email_mode === value ? 'chosen' : ''}`}><input type="radio" name="email_mode" value={value} checked={draft.email_mode === value} onChange={() => change({email_mode: value})} /><span><strong>{label}</strong><small>{help}</small></span></label>)}</div>
            {(draft.email_mode === 'daily' || draft.email_mode === 'weekly') && <div className="form-grid">{draft.email_mode === 'weekly' && <Field label="Day"><Select value={draft.digest_weekday} onChange={e => change({digest_weekday: Number(e.target.value)})}>{weekdays.map((day, index) => <option value={index} key={day}>{day}</option>)}</Select></Field>}<Field label="Time"><Select value={draft.digest_hour} onChange={e => change({digest_hour: Number(e.target.value)})}>{hours.map(hour => <option key={hour} value={hour}>{hourLabel(hour)}</option>)}</Select></Field></div>}
          </div>
        </section>
        <section className="settings-section"><header><h2>Reminders</h2><p>Counted from the first alert. They stop once you apply or dismiss, pause the target, or the posting closes.</p></header>
          <div className="settings-fields"><Field label="Remind me after (days)" hint="Separate days with commas, such as 1, 3, 7. Leave empty for none."><Input value={reminders} onChange={e => {setReminders(e.target.value); setSaved(false)}} placeholder="1, 3" /></Field><div className="form-grid"><Field label="Quiet from"><Select value={draft.quiet_start ?? ''} onChange={e => change({quiet_start: e.target.value === '' ? null : Number(e.target.value)})}><option value="">Off</option>{hours.map(hour => <option key={hour} value={hour}>{hourLabel(hour)}</option>)}</Select></Field><Field label="Quiet until"><Select value={draft.quiet_end ?? ''} onChange={e => change({quiet_end: e.target.value === '' ? null : Number(e.target.value)})}><option value="">Off</option>{hours.map(hour => <option key={hour} value={hour}>{hourLabel(hour)}</option>)}</Select></Field><Field label="Emails per day, at most"><Input required type="number" min="1" max="100" value={draft.daily_email_cap} onChange={e => change({daily_email_cap: Number(e.target.value)})} /></Field></div></div>
        </section>
        <section className="settings-section"><header><h2>Research</h2><p>Research sends the company, role, location, start, notes, and your links to Anthropic.</p></header>
          <div className="settings-fields"><Field label="Monthly budget (USD)" hint="Research stops for the month when its estimated cost reaches this. Watching works without it."><Input type="number" min="0" max="1000" step="0.5" value={draft.research_monthly_budget_usd} onChange={e => change({research_monthly_budget_usd: Number(e.target.value)})} /></Field></div>
        </section>
        {error && <p className="error-box settings-error" role="alert">{error}</p>}
        <div className="settings-save"><span role="status">{saved ? 'Saved' : ''}</span><Button type="submit" variant="primary" busy={busy === 'save'} disabled={!!busy}>Save preferences</Button></div>
      </div>
      <aside className="settings-aside">
        <section className="aside-block"><h2>Schedule</h2><dl className="facts stacked"><div><dt>Checks</dt><dd>{hoursText(draft.check_interval_hours)}</dd></div><div><dt>Alerts</dt><dd>{emailText}</dd></div><div><dt>Reminders</dt><dd>{reminderText}</dd></div>{draft.quiet_start !== null && draft.quiet_end !== null && <div><dt>Quiet hours</dt><dd>{hourLabel(draft.quiet_start)} to {hourLabel(draft.quiet_end)}</dd></div>}<div><dt>Timezone</dt><dd>{draft.timezone.replaceAll('_', ' ')}</dd></div></dl></section>
        <section className="aside-block"><h2>Connections</h2><dl className="facts stacked"><div><dt>Research</dt><dd>{health.mode === 'demo' ? 'Demo data' : health.configuration.ai ? 'On' : 'Off, no API key'}</dd></div><div><dt>Email</dt><dd>{{preview: 'Previews only, nothing is sent', smtp: 'SMTP', resend: 'Resend'}[health.configuration.email_transport]}</dd></div></dl>{health.configuration.email_transport !== 'preview' && !health.configuration.email && <p className="aside-note error-text">The email transport is missing EMAIL_FROM or its credentials.</p>}<Button disabled={!!busy} busy={busy === 'test'} onClick={async () => {setBusy('test'); setError(''); setTestMessage(false); try {await onTest(); setTestMessage(true)} catch (e) {setError(messageOf(e))} finally {setBusy('')}}}>Send a test email</Button>{testMessage && <p className="aside-note" role="status">Queued. Activity shows the result.</p>}</section>
        <section className="aside-block"><h2>Account</h2><dl className="facts stacked"><div><dt>Email</dt><dd className="address">{account.split('@')[0]}<wbr />{account.includes('@') && `@${account.split('@').slice(1).join('@')}`}</dd></div></dl><div className="aside-actions"><Button onClick={onSignOut}>Sign out</Button><button type="button" className="link-button danger-link" onClick={() => setDeleting(true)}>Delete account</button></div></section>
      </aside>
    </form>
    {deleting && <Modal title="Delete your account?" onClose={closeDelete}><form onSubmit={async e => {e.preventDefault(); setBusy('delete'); setDeleteError(''); try {await onDeleteAccount(password)} catch (err) {setDeleteError(messageOf(err)); setBusy('')}}}>
      <div className="modal-body">
        <p>This deletes {account} with every target, its research and openings, your email history, and these preferences. It can't be undone.</p>
        <p className="form-description"><a href="/api/exports/targets?format=xlsx" download>Download your watchlist</a> first if you want a copy.</p>
        <Field label="Password"><Input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></Field>
        {deleteError && <p className="error-box" role="alert">{deleteError}</p>}
      </div>
      <div className="modal-footer"><Button onClick={closeDelete}>Keep my account</Button><Button type="submit" variant="danger" busy={busy === 'delete'} disabled={!password}>Delete account</Button></div>
    </form></Modal>}
  </>
}
