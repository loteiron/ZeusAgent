import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { buildDesktopBackendEnv } from './backend-env'

type Runtime = {
  root: string
  python: string
  venvRoot: string
  version: string
  commit: string
  env: NodeJS.ProcessEnv
}

type Progress = { stage: string; message: string }
type RuntimeOptions = { manifestPath: string; signal?: AbortSignal; onProgress?: (event: Progress) => void }
type RuntimeModule = {
  readCachedWindowsRuntime: (options: { manifestPath: string }) => Promise<Runtime | null>
  ensureWindowsRuntime: (options: RuntimeOptions) => Promise<Runtime>
}
type BootstrapEvent = Record<string, unknown>
const INSTALL_STAGES = ['runtime-files', 'python', 'dependencies', 'verify']

export function packagedWindowsManifest({
  isPackaged,
  platform,
  resourcesPath
}: {
  isPackaged: boolean
  platform: string
  resourcesPath: string
}) {
  // A broken release must surface its own missing payload, never discover its
  // installed zeus.cmd on PATH and recursively launch the same Desktop binary.
  return isPackaged && platform === 'win32' ? path.win32.join(resourcesPath, 'backend', 'runtime-manifest.json') : null
}

async function loadRuntimeModule(manifestPath: string): Promise<RuntimeModule> {
  const url = pathToFileURL(path.join(path.dirname(manifestPath), 'windows-runtime.mjs')).href

  return await import(/* @vite-ignore */ url)
}

/** The release helper owns installation; Electron owns its observable lifecycle. */
export function createPackagedWindowsRuntime({
  manifestPath,
  loadModule = loadRuntimeModule
}: {
  manifestPath: string
  loadModule?: (manifestPath: string) => Promise<RuntimeModule>
}) {
  let cached: Runtime | null = null
  let pending: Promise<Runtime> | null = null
  let failure: Error | null = null

  return {
    peek: () => cached,
    reset() {
      cached = null
      failure = null
    },
    async readCached() {
      if (!cached) {
        cached = await (await loadModule(manifestPath)).readCachedWindowsRuntime({ manifestPath })
      }

      return cached
    },
    async ensure({
      signal,
      onEvent = () => {}
    }: {
      signal?: AbortSignal
      onEvent?: (event: BootstrapEvent) => void
    } = {}): Promise<Runtime> {
      if (failure) {
        throw failure
      }

      if (cached) {
        return cached
      }

      if (pending) {
        return await pending
      }

      pending = (async () => {
        let stage: string | null = null
        onEvent({ type: 'manifest', stages: INSTALL_STAGES.map(name => ({ name })), protocolVersion: null })

        try {
          const module = await loadModule(manifestPath)

          const runtime = await module.ensureWindowsRuntime({
            manifestPath,
            signal,
            onProgress: progress => {
              const nextStage = ['waiting', 'download', 'extract'].includes(progress.stage)
                ? 'runtime-files'
                : progress.stage === 'ready'
                  ? 'verify'
                  : progress.stage

              if (stage !== nextStage) {
                if (stage) {
                  onEvent({ type: 'stage', name: stage, state: 'succeeded' })
                }

                stage = nextStage
                onEvent({ type: 'stage', name: stage, state: 'running' })
              }

              onEvent({ type: 'log', stage, line: progress.message, stream: 'stdout' })
            }
          })

          signal?.throwIfAborted()
          cached = runtime

          if (stage) {
            onEvent({ type: 'stage', name: stage, state: 'succeeded' })
          }

          onEvent({ type: 'complete' })

          return runtime
        } catch (cause) {
          const cancelled = Boolean(signal?.aborted)

          const message = cancelled
            ? 'ZeusAgent install was cancelled.'
            : `ZeusAgent runtime setup failed: ${cause instanceof Error ? cause.message : String(cause)}`

          failure = Object.assign(new Error(message, { cause }), {
            isBootstrapFailure: true,
            bootstrapCancelled: cancelled,
            failedStage: stage
          })

          if (stage) {
            onEvent({ type: 'stage', name: stage, state: 'failed', error: message })
          }

          onEvent({ type: 'failed', error: message })
          throw failure
        }
      })()

      try {
        return await pending
      } finally {
        pending = null
      }
    }
  }
}

export function buildPackagedWindowsBackend(runtime: Runtime, backendArgs: string[], zeusHome: string) {
  return {
    kind: 'python',
    label: `ZeusAgent ${runtime.version} at ${runtime.root}`,
    command: runtime.python,
    args: ['-m', 'zeus_cli.main', ...backendArgs],
    env: {
      ...runtime.env,
      ...buildDesktopBackendEnv({
        zeusHome,
        pythonPathEntries: [runtime.root, path.win32.join(runtime.venvRoot, 'Lib', 'site-packages')],
        venvRoot: runtime.venvRoot,
        currentEnv: runtime.env,
        platform: 'win32'
      })
    },
    root: runtime.root,
    bootstrap: false,
    shell: false
  }
}
