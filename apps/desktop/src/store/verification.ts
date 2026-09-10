import { atom } from 'nanostores'

export type EvidenceFreshness = 'current' | 'stale' | 'unknown' | 'not_run'
export type EvidenceComparison = 'regression' | 'fixed' | 'persistent_failure' | 'unchanged' | 'new' | 'incomparable'

export interface EvidenceCheck {
  id: number | string
  command: string
  canonical_command: string
  kind: string
  scope: string
  status: 'passed' | 'failed' | 'running'
  exit_code: number | null
  cwd: string
  created_at: string
  output_summary: string
  freshness: EvidenceFreshness
  comparison: EvidenceComparison
}

export interface EvidenceBaseline {
  id: number | string
  created_at: string
  fingerprint: string
  check_count: number
}

export interface VerificationSnapshot {
  status: string
  session_id: string
  root: string
  changed_paths: string[]
  checks: EvidenceCheck[]
  summary: { passed: number; failed: number; stale: number; unknown: number; total: number }
  workspace: {
    root: string
    fingerprint: string
    head: string
    status: string
    reason: string
    changed_paths: string[]
  }
  baseline: EvidenceBaseline | null
}

export interface EvidenceState {
  data: VerificationSnapshot | null
  error: string | null
  loading: boolean
  pending: 'capture' | 'clear' | null
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string')

const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const freshnessValues = new Set(['current', 'stale', 'unknown', 'not_run'])
const comparisonValues = new Set(['regression', 'fixed', 'persistent_failure', 'unchanged', 'new', 'incomparable'])

/** Read the evidence contract strictly: an older/partial response cannot become a green result. */
export function parseVerification(value: unknown): VerificationSnapshot | null {
  if (!record(value) || !Array.isArray(value.checks) || !record(value.summary) || !record(value.workspace)) {
    return null
  }

  if (typeof value.status !== 'string' || typeof value.root !== 'string' || typeof value.session_id !== 'string') {
    return null
  }

  if (!strings(value.changed_paths) || !strings(value.workspace.changed_paths)) {
    return null
  }

  const checks: EvidenceCheck[] = []

  for (const item of value.checks) {
    if (
      !record(item) ||
      !(typeof item.id === 'string' || number(item.id)) ||
      !(item.exit_code === null || number(item.exit_code))
    ) {
      return null
    }

    if (
      !['command', 'canonical_command', 'kind', 'scope', 'cwd', 'created_at', 'output_summary'].every(
        key => typeof item[key] === 'string'
      )
    ) {
      return null
    }

    if (item.status !== 'passed' && item.status !== 'failed' && item.status !== 'running') {
      return null
    }

    if (!freshnessValues.has(String(item.freshness)) || !comparisonValues.has(String(item.comparison))) {
      return null
    }

    checks.push(item as unknown as EvidenceCheck)
  }

  if (
    !['passed', 'failed', 'stale', 'unknown', 'total'].every(key =>
      number(value.summary && (value.summary as Record<string, unknown>)[key])
    )
  ) {
    return null
  }

  if (
    !['root', 'fingerprint', 'head', 'status', 'reason'].every(
      key => typeof (value.workspace as Record<string, unknown>)[key] === 'string'
    )
  ) {
    return null
  }

  if (value.baseline !== null) {
    if (
      !record(value.baseline) ||
      !(typeof value.baseline.id === 'string' || number(value.baseline.id)) ||
      typeof value.baseline.created_at !== 'string' ||
      typeof value.baseline.fingerprint !== 'string' ||
      !number(value.baseline.check_count)
    ) {
      return null
    }
  }

  return { ...value, checks } as unknown as VerificationSnapshot
}

/** One visible session/workspace owns one controller. Closing or changing that scope disposes it. */
export function createEvidenceController(request: (method: string) => Promise<unknown>, expectedSessionIds?: string[]) {
  const state = atom<EvidenceState>({ data: null, error: null, loading: false, pending: null })
  let generation = 0
  let disposed = false
  let readInFlight: Promise<void> | null = null
  let readAgain = false

  const publish = (next: Partial<EvidenceState>) => {
    if (!disposed) {
      state.set({ ...state.get(), ...next })
    }
  }

  const failure = (error: unknown) =>
    error instanceof Error ? error.message.slice(0, 500) : String(error).slice(0, 500)

  function refresh(afterMutation = false): Promise<void> {
    if (disposed || (state.get().pending && !afterMutation)) {
      return Promise.resolve()
    }

    if (readInFlight) {
      readAgain = true

      return readInFlight
    }

    const token = generation

    const operation = (async () => {
      do {
        readAgain = false
        publish({ loading: true })

        try {
          const response = await request('verification.status')

          if (disposed || token !== generation) {return}
          const data = record(response) ? parseVerification(response.verification) : null

          if (!data) {throw new Error('Evidence is unavailable from this backend. Update the runtime and retry.')}

          if (expectedSessionIds && !expectedSessionIds.includes(data.session_id)) {throw new Error('Evidence belongs to another session. Refresh after the workspace finishes connecting.')}
          publish({ data, error: null, loading: false })
        } catch (error) {
          if (token === generation) {publish({ error: failure(error), loading: false })}
        }
      } while (readAgain && !disposed && token === generation)
    })()

    const completion = operation.finally(() => { if (readInFlight === completion) {readInFlight = null} })
    readInFlight = completion

    return readInFlight
  }

  async function baseline(action: 'capture' | 'clear'): Promise<void> {
    if (disposed || state.get().pending || state.get().loading) {
      return
    }

    const token = ++generation
    publish({ pending: action, loading: false, error: null })

    try {
      const response = await request(`verification.baseline.${action}`)

      if (disposed || token !== generation) {
        return
      }

      if (!record(response) || (action === 'capture' ? !record(response.baseline) : typeof response.cleared !== 'boolean')) {
        throw new Error('The baseline change was not confirmed. Refresh and retry.')
      }

      await refresh(true)
    } catch (error) {
      if (token === generation) {
        publish({ error: failure(error) })
      }
    } finally {
      if (token === generation) {publish({ pending: null })}
    }
  }

  return {
    state,
    refresh,
    baseline,
    activate: () => {
      disposed = false
      generation += 1
      readAgain = false
      readInFlight = null
      publish({ loading: false, pending: null })
    },
    dispose: () => {
      disposed = true
      generation += 1
      readAgain = false
    }
  }
}
