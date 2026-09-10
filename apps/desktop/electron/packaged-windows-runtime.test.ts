import path from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import {
  buildPackagedWindowsBackend,
  createPackagedWindowsRuntime,
  packagedWindowsManifest
} from './packaged-windows-runtime'
import { runPrimaryBackendStartup } from './primary-backend-startup'

const runtime = {
  root: 'C:\\Local\\ZeusAgent\\runtimes\\0.22-hash\\source\\zeus-agent',
  python: 'C:\\Local\\ZeusAgent\\runtimes\\0.22-hash\\source\\zeus-agent\\.venv\\Scripts\\python.exe',
  venvRoot: 'C:\\Local\\ZeusAgent\\runtimes\\0.22-hash\\source\\zeus-agent\\.venv',
  version: '0.22.0',
  commit: 'release-commit',
  env: { Path: 'C:\\PrivateGit\\cmd;C:\\PrivateNode', ZEUS_GIT_BASH_PATH: 'C:\\PrivateGit\\bin\\bash.exe' }
}

function fixture(cached: typeof runtime | null = null) {
  const module = {
    readCachedWindowsRuntime: vi.fn(async () => cached),
    ensureWindowsRuntime: vi.fn(
      async (_options: { signal?: AbortSignal; onProgress?: (event: { stage: string; message: string }) => void }) =>
        runtime
    )
  }

  const loadModule = vi.fn(async () => module)

  return {
    module,
    loadModule,
    controller: createPackagedWindowsRuntime({
      manifestPath: 'C:\\App\\resources\\backend\\runtime-manifest.json',
      loadModule
    })
  }
}

describe('packaged Windows runtime', () => {
  it('selects release resources only for packaged Windows, even before files are available', () => {
    expect(packagedWindowsManifest({ isPackaged: true, platform: 'win32', resourcesPath: 'C:\\App\\resources' })).toBe(
      path.win32.join('C:\\App\\resources', 'backend', 'runtime-manifest.json')
    )
    expect(packagedWindowsManifest({ isPackaged: false, platform: 'win32', resourcesPath: '/resources' })).toBeNull()
    expect(packagedWindowsManifest({ isPackaged: true, platform: 'darwin', resourcesPath: '/resources' })).toBeNull()
  })

  it('reads a ready runtime without installing and builds the backend from its actual interpreter and private tools', async () => {
    const { module, controller } = fixture(runtime)
    expect(await controller.readCached()).toBe(runtime)
    expect(controller.peek()).toBe(runtime)
    expect(module.ensureWindowsRuntime).not.toHaveBeenCalled()
    const backend = buildPackagedWindowsBackend(runtime, ['--profile', 'work', 'serve'], 'C:\\ZeusHome')
    expect(backend.command).toBe(runtime.python)
    expect(backend.args).toEqual(['-m', 'zeus_cli.main', '--profile', 'work', 'serve'])
    expect(backend.root).toBe(runtime.root)
    expect(backend.bootstrap).toBe(false)
    expect(backend.env.ZEUS_GIT_BASH_PATH).toBe(runtime.env.ZEUS_GIT_BASH_PATH)
    expect(backend.env.Path).toContain(runtime.env.Path)
    expect(backend.env.PYTHONPATH.split(';')).toEqual([
      runtime.root,
      path.win32.join(runtime.venvRoot, 'Lib', 'site-packages')
    ])
  })

  it('coalesces setup, reports actual stages and caches only completed runtime', async () => {
    const { module, controller } = fixture()
    const events: Array<Record<string, unknown>> = []
    let finish!: (value: typeof runtime) => void
    module.ensureWindowsRuntime.mockImplementation(async ({ onProgress }) => {
      onProgress?.({ stage: 'python', message: 'Installing Python' })

      return await new Promise(resolve => {
        finish = resolve
      })
    })
    const signal = new AbortController().signal
    const first = controller.ensure({ signal, onEvent: event => events.push(event) })
    const second = controller.ensure({ signal })
    await vi.waitFor(() => expect(module.ensureWindowsRuntime).toHaveBeenCalledTimes(1))
    expect(controller.peek()).toBeNull()
    expect(module.ensureWindowsRuntime.mock.calls[0][0].signal).toBe(signal)
    expect(events[0]).toMatchObject({ type: 'manifest', stages: expect.arrayContaining([{ name: 'python' }]) })
    expect(events).toContainEqual({ type: 'stage', name: 'python', state: 'running' })
    finish(runtime)
    expect(await first).toBe(runtime)
    expect(await second).toBe(runtime)
    expect(controller.peek()).toBe(runtime)
    expect(events).toContainEqual({ type: 'stage', name: 'python', state: 'succeeded' })
    expect(events.at(-1)).toEqual({ type: 'complete' })
  })

  it('latches cancelled setup without caching or retrying until explicit reset', async () => {
    const { module, controller } = fixture()
    const abort = new AbortController()
    const events: Array<Record<string, unknown>> = []
    module.ensureWindowsRuntime.mockImplementation(async ({ signal }) => {
      abort.abort()
      signal?.throwIfAborted()

      return runtime
    })
    await expect(
      controller.ensure({ signal: abort.signal, onEvent: event => events.push(event) })
    ).rejects.toMatchObject({ isBootstrapFailure: true, bootstrapCancelled: true })
    expect(controller.peek()).toBeNull()
    await expect(controller.ensure()).rejects.toThrow('cancelled')
    expect(module.ensureWindowsRuntime).toHaveBeenCalledTimes(1)
    expect(events.at(-1)).toMatchObject({ type: 'failed', error: expect.stringContaining('cancelled') })
    controller.reset()
    module.ensureWindowsRuntime.mockResolvedValue(runtime)
    expect(await controller.ensure()).toBe(runtime)
    expect(module.ensureWindowsRuntime).toHaveBeenCalledTimes(2)
  })

  it('remote startup never loads local payload; local startup waits for the setup choice', async () => {
    const { module, controller } = fixture()
    const backend = { kind: 'bootstrap-needed', bundledManifest: 'manifest' }
    let allowLocal!: (choice: 'continue-local') => void

    const options = {
      resolveRemote: vi.fn(async () => ({ baseUrl: 'https://gateway.example' })),
      connectRemote: vi.fn(async remote => remote),
      prepareLocalBackend: vi.fn(async () => {
        await controller.readCached()

        return backend
      }),
      ensureLocalRuntime: vi.fn(async () => controller.ensure()),
      waitForLocalStart: vi.fn(async () => {}),
      waitForDecision: vi.fn(
        async () =>
          new Promise<'continue-local'>(resolve => {
            allowLocal = resolve
          })
      )
    }

    expect((await runPrimaryBackendStartup(options)).kind).toBe('remote')
    expect(module.readCachedWindowsRuntime).not.toHaveBeenCalled()
    expect(module.ensureWindowsRuntime).not.toHaveBeenCalled()
    options.resolveRemote.mockResolvedValue(null)
    const pending = runPrimaryBackendStartup(options)
    await vi.waitFor(() => expect(options.waitForDecision).toHaveBeenCalled())
    expect(module.ensureWindowsRuntime).not.toHaveBeenCalled()
    allowLocal('continue-local')
    expect((await pending).kind).toBe('local')
    expect(module.ensureWindowsRuntime).toHaveBeenCalledTimes(1)
  })
})
