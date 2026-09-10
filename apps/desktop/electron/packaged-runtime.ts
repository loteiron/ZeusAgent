export type PackagedRuntime = {
  root: string
  python: string
  venvRoot: string
  version: string
  commit: string
  env: NodeJS.ProcessEnv
}

type Progress = { stage: string; message: string }
export type RuntimeOptions = { manifestPath: string; signal?: AbortSignal; onProgress?: (event: Progress) => void }
export type RuntimeModule = {
  readCachedRuntime: (options: { manifestPath: string }) => Promise<PackagedRuntime | null>
  ensureRuntime: (options: RuntimeOptions) => Promise<PackagedRuntime>
}
type BootstrapEvent = Record<string, unknown>
const INSTALL_STAGES = ['runtime-files', 'python', 'dependencies', 'verify']

/** The release helper owns installation; Electron owns its observable lifecycle. */
export function createPackagedRuntime({
  manifestPath,
  loadModule
}: {
  manifestPath: string
  loadModule: (manifestPath: string) => Promise<RuntimeModule>
}) {
  let cached: PackagedRuntime | null = null
  let pending: Promise<PackagedRuntime> | null = null
  let failure: Error | null = null

  return {
    peek: () => cached,
    reset() {
      cached = null
      failure = null
    },
    async readCached() {
      if (!cached) {
        cached = await (await loadModule(manifestPath)).readCachedRuntime({ manifestPath })
      }

      return cached
    },
    async ensure({
      signal,
      onEvent = () => {}
    }: {
      signal?: AbortSignal
      onEvent?: (event: BootstrapEvent) => void
    } = {}): Promise<PackagedRuntime> {
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

          const runtime = await module.ensureRuntime({
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
