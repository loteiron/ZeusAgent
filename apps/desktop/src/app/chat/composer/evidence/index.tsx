import { useStore } from '@nanostores/react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog'
import { useI18n } from '@/i18n'
import { evidenceMessages, type EvidenceMessages } from '@/i18n/evidence'
import { $selectedStoredSessionId, $workspaceCwdOwner } from '@/store/session'
import type { EvidenceCheck, VerificationSnapshot } from '@/store/verification'
import type { ZeusAgentGateway } from '@/zeus'

import { useEvidence } from './use-evidence'

interface EvidenceProps {
  sessionId: string
  cwd: string
  gateway: ZeusAgentGateway | null
  requirePrimaryOwnership?: boolean
}

export function evidenceTime(value: string | number, locale: string): string {
  const date = new Date(typeof value === 'number' ? value * 1000 : value)

  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(locale)
}

export function EvidenceButton({ requirePrimaryOwnership, ...props }: EvidenceProps) {
  const { locale } = useI18n()
  const selected = useStore($selectedStoredSessionId)
  const owner = useStore($workspaceCwdOwner)
  const [open, setOpen] = useState(false)
  const m = evidenceMessages[locale]
  const ready = !requirePrimaryOwnership || owner === selected

  if (!ready) {
    return null
  }

  return (
    <Dialog onOpenChange={setOpen} open={open}>
      <DialogTrigger asChild>
        <Button className="shrink-0 gap-1 text-primary" size="micro" type="button" variant="text">
          <Codicon name="checklist" size="0.8rem" />
          {m.title}
        </Button>
      </DialogTrigger>
      {open && <EvidenceDialog key={`${props.sessionId}:${props.cwd}`} {...props} />}
    </Dialog>
  )
}

function EvidenceDialog({ sessionId, cwd, gateway }: EvidenceProps) {
  const { locale } = useI18n()
  const m = evidenceMessages[locale]
  const state = useEvidence(sessionId, cwd, gateway)
  const data = state.data

  return (
    <DialogContent
      bodyClassName="max-h-[min(80vh,52rem)] overflow-y-auto"
      className="sm:max-w-3xl"
      data-testid="evidence-dialog"
    >
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Codicon className="text-primary" name="checklist" />
          {m.title}
        </DialogTitle>
        <DialogDescription>{m.description}</DialogDescription>
      </DialogHeader>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={state.loading || Boolean(state.pending)}
          onClick={() => void state.refresh()}
          size="sm"
          variant="outline"
        >
          {state.error ? m.retry : m.refresh}
        </Button>
        <Button
          disabled={
            !data?.checks.length ||
            state.loading ||
            Boolean(state.pending) ||
            Boolean(state.error) ||
            data.workspace.status !== 'ready'
          }
          onClick={() => void state.baseline('capture')}
          size="sm"
          variant="outline"
        >
          {m.capture}
        </Button>
        {data?.baseline && (
          <Button
            disabled={state.loading || Boolean(state.pending)}
            onClick={() => void state.baseline('clear')}
            size="sm"
            variant="text"
          >
            {m.clear}
          </Button>
        )}
        <span aria-live="polite" className="text-xs text-muted-foreground">
          {state.loading || state.pending ? m.loading : ''}
        </span>
      </div>
      {state.error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm" role="alert">
          <strong>{m.unavailable}</strong>
          <p className="mt-1 break-words">{state.error}</p>
          {data && <p className="mt-1">{m.historical}</p>}
        </div>
      )}
      {data && <EvidenceResults data={data} historical={Boolean(state.error)} locale={locale} messages={m} />}
      {!data && !state.error && <p className="py-6 text-center text-sm text-muted-foreground">{m.loading}</p>}
    </DialogContent>
  )
}

interface EvidenceResultsProps {
  data: VerificationSnapshot
  historical?: boolean
  locale: string
  messages: EvidenceMessages
}

export function EvidenceResults({ data, historical, locale, messages: m }: EvidenceResultsProps) {
  const changedPaths = data.workspace.changed_paths

  const counts = [
    ['passed', data.summary.passed],
    ['failed', data.summary.failed],
    ['stale', data.summary.stale],
    ['unknown', data.summary.unknown]
  ] as const

  return (
    <div className="space-y-4">
      <div className="border-s-2 border-primary bg-primary/5 px-3 py-2">
        <div className="text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground">{m.workspace}</div>
        <div className="mt-1 break-all font-mono text-xs" dir="ltr">
          {data.workspace.root || data.root}
        </div>
        {data.workspace.head && (
          <div className="mt-1 font-mono text-[0.65rem] text-muted-foreground" title={data.workspace.fingerprint}>
            {data.workspace.head.slice(0, 12)} · {m.fingerprint}: {data.workspace.fingerprint.slice(0, 12) || '—'}
          </div>
        )}
        {data.workspace.reason && <p className="mt-1 text-xs text-muted-foreground">{data.workspace.reason}</p>}
      </div>
      <dl aria-label={m.total} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {counts.map(([kind, count]) => (
          <div
            className="flex items-baseline justify-between gap-2 rounded border border-(--ui-stroke-tertiary) px-3 py-2"
            key={kind}
          >
            <dt className="text-xs text-muted-foreground">{m[kind]}</dt>
            <dd
              className={`font-mono text-lg tabular-nums ${kind === 'failed' && count > 0 ? 'text-destructive' : ''}`}
            >
              {count}
            </dd>
          </div>
        ))}
      </dl>
      <section className="rounded-md border border-(--ui-stroke-tertiary) p-3">
        <h3 className="text-xs font-semibold">{m.baseline}</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {data.baseline
            ? `${evidenceTime(data.baseline.created_at, locale)} · ${data.baseline.check_count} ${m.total.toLocaleLowerCase(locale)}`
            : m.noBaseline}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">{m.baselineHelp}</p>
      </section>
      {data.checks.length === 0 ? (
        <div className="py-6 text-center">
          <h3 className="text-sm font-semibold">{m.empty}</h3>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">{m.emptyHelp}</p>
        </div>
      ) : (
        <section aria-label={m.checks} className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">
              {m.checks} <span className="font-mono text-muted-foreground">{data.summary.total}</span>
            </h3>
            <p className="text-xs text-muted-foreground">{m.scopeHelp}</p>
          </div>
          {data.checks.map(check => (
            <EvidenceCheckRow check={check} historical={historical} key={check.id} locale={locale} messages={m} />
          ))}
        </section>
      )}
      {changedPaths.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer rounded py-1 focus-visible:outline-2 focus-visible:outline-primary">
            {m.changes} ({changedPaths.length})
          </summary>
          <ul className="mt-2 space-y-1 break-all font-mono" dir="ltr">
            {changedPaths.map(path => (
              <li key={path}>{path}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function EvidenceCheckRow({
  check,
  historical,
  locale,
  messages: m
}: {
  check: EvidenceCheck
  historical?: boolean
  locale: string
  messages: EvidenceMessages
}) {
  return (
    <article className="overflow-hidden rounded-md border border-(--ui-stroke-tertiary)" data-testid="evidence-check">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-(--ui-stroke-tertiary) bg-primary/4 px-3 py-2 text-xs">
        <span className={check.status === 'failed' ? 'font-semibold text-destructive' : 'font-semibold'}>
          {m.observed}: {m[check.status]}{' '}
          {check.exit_code !== null && (
            <span className="font-normal text-muted-foreground">
              · {m.exit} {check.exit_code}
            </span>
          )}
        </span>
        <span className={check.freshness === 'stale' ? 'font-semibold text-primary' : 'text-muted-foreground'}>
          {m.freshness}: {m[historical ? 'unknown' : check.freshness]}
        </span>
      </div>
      <div className="space-y-2 px-3 py-3">
        <code className="block whitespace-pre-wrap break-all text-xs" dir="ltr">
          {check.command}
        </code>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[0.7rem] text-muted-foreground">
          <span>{check.scope === 'targeted' ? m.targeted : m.full}</span>
          <span>{m[check.comparison]}</span>
          <time dateTime={check.created_at}>{evidenceTime(check.created_at, locale)}</time>
        </div>
        <div className="break-all font-mono text-[0.65rem] text-muted-foreground" dir="ltr">
          {check.cwd}
        </div>
        <details>
          <summary className="cursor-pointer rounded text-xs focus-visible:outline-2 focus-visible:outline-primary">
            {m.output}
          </summary>
          <pre
            className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-all rounded bg-(--ui-control-active-background)/30 p-2 font-mono text-[0.7rem] leading-relaxed"
            dir="ltr"
          >
            {check.output_summary || m.noOutput}
          </pre>
        </details>
      </div>
    </article>
  )
}
