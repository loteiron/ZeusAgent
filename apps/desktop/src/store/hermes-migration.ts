import { atom } from 'nanostores'

export type MigrationCategory = 'chats' | 'settings' | 'memories' | 'skills' | 'prompts' | 'profiles'
export interface MigrationPreview {
  scan_id: string
  source: string
  target: string
  categories: { id: MigrationCategory; label: string; count: number; conflicts: number }[]
  warnings: string[]
}
export interface MigrationResult {
  source: string
  target: string
  imported: Record<string, number>
  skipped: Record<string, number>
  conflicts: number
  backup_path: string | null
  warnings: string[]
  restart_required: boolean
}
interface MigrationState {
  source: string
  preview: MigrationPreview | null
  result: MigrationResult | null
  selected: MigrationCategory[]
  busy: 'scan' | 'import' | null
  error: string | null
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const isStrings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string')

const categories = new Set(['chats', 'settings', 'memories', 'skills', 'prompts', 'profiles'])

function parsePreview(value: unknown): MigrationPreview | null {
  if (
    !isRecord(value) ||
    !['scan_id', 'source', 'target'].every(key => typeof value[key] === 'string') ||
    !Array.isArray(value.categories) ||
    !isStrings(value.warnings)
  ) {
    return null
  }

  if (
    !value.categories.every(
      item =>
        isRecord(item) &&
        categories.has(String(item.id)) &&
        typeof item.label === 'string' &&
        Number.isInteger(item.count) &&
        Number.isInteger(item.conflicts)
    )
  ) {
    return null
  }

  return value as unknown as MigrationPreview
}

function parseResult(value: unknown): MigrationResult | null {
  if (
    !isRecord(value) ||
    typeof value.source !== 'string' ||
    typeof value.target !== 'string' ||
    !isRecord(value.imported) ||
    !isRecord(value.skipped) ||
    !isStrings(value.warnings) ||
    typeof value.restart_required !== 'boolean' ||
    !Number.isInteger(value.conflicts) ||
    !(value.backup_path === null || typeof value.backup_path === 'string')
  ) {
    return null
  }

  if (
    ![...Object.values(value.imported), ...Object.values(value.skipped)].every(
      item => Number.isInteger(item) && Number(item) >= 0
    )
  ) {
    return null
  }

  return value as unknown as MigrationResult
}

/** A preview and its import always use the same captured gateway/profile request. */
export function createHermesMigrationController(
  request: (method: string, params: Record<string, unknown>) => Promise<unknown>
) {
  const state = atom<MigrationState>({ source: '', preview: null, result: null, selected: [], busy: null, error: null })
  let version = 0
  let disposed = false

  const publish = (patch: Partial<MigrationState>) => {
    if (!disposed) {
      state.set({ ...state.get(), ...patch })
    }
  }

  const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error)).slice(0, 600)

  const setSource = (source: string) => {
    if (state.get().busy === 'import') {
      return
    }

    version += 1
    publish({ source, preview: null, result: null, selected: [], error: null, busy: null })
  }

  const select = (id: MigrationCategory, checked: boolean) => {
    if (state.get().busy || !state.get().preview?.categories.some(item => item.id === id && item.count > 0)) {
      return
    }

    publish({
      selected: checked ? [...new Set([...state.get().selected, id])] : state.get().selected.filter(item => item !== id)
    })
  }

  async function scan() {
    if (disposed || state.get().busy === 'import') {
      return
    }

    const token = ++version
    const source = state.get().source.trim()
    publish({ busy: 'scan', error: null, result: null, preview: null, selected: [] })

    try {
      const response = await request('hermes.migration.scan', source ? { source } : {})

      if (disposed || token !== version) {
        return
      }

      const preview = isRecord(response) ? parsePreview(response.preview) : null

      if (!preview) {
        throw new Error('The agent returned an incomplete migration preview. Update the runtime and retry.')
      }

      publish({ preview, selected: preview.categories.filter(item => item.count > 0).map(item => item.id), busy: null })
    } catch (error) {
      if (token === version) {
        publish({ error: errorText(error), busy: null })
      }
    }
  }

  async function importSelected() {
    const current = state.get()

    if (disposed || current.busy || !current.preview || !current.selected.length) {
      return
    }

    const token = ++version
    publish({ busy: 'import', error: null, result: null })

    try {
      const response = await request('hermes.migration.import', {
        source: current.preview.source,
        scan_id: current.preview.scan_id,
        categories: current.selected
      })

      if (disposed || token !== version) {
        return
      }

      const result = isRecord(response) ? parseResult(response.result) : null

      if (!result) {
        throw new Error('The import result could not be confirmed. Scan again before retrying.')
      }

      publish({ result, preview: null, selected: [], busy: null })
    } catch (error) {
      if (token === version) {
        publish({
          error: `The import could not be confirmed and may still be running on the agent. Wait for it to finish, then scan again before retrying. ${errorText(error)}`,
          busy: null,
          preview: null,
          selected: []
        })
      }
    }
  }

  return {
    state,
    setSource,
    select,
    scan,
    importSelected,
    activate: () => {
      disposed = false
      version += 1
      publish({ busy: null })
    },
    dispose: () => {
      disposed = true
      version += 1
    }
  }
}
