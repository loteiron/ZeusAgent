import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { buildPackagedLinuxBackend, createPackagedLinuxRuntime, packagedLinuxManifest } from './packaged-linux-runtime'
import { runPrimaryBackendStartup } from './primary-backend-startup'

const runtime = {
  root: '/home/user/.local/share/ZeusAgent/runtimes/release/source/zeus-agent',
  python: '/home/user/.local/share/ZeusAgent/runtimes/release/source/zeus-agent/.venv/bin/python',
  venvRoot: '/home/user/.local/share/ZeusAgent/runtimes/release/source/zeus-agent/.venv',
  version: '0.22.0',
  commit: 'linux-release',
  env: {
    ZEUS_HOME: '/home/user/.zeus',
    PATH: '/private/node/bin:/usr/bin',
    ZEUS_NODE: '/private/node/bin/node',
    ZEUS_TUI_DIR: '/private/ui-tui'
  }
}

describe('packaged Linux runtime', () => {
  it('selects the bundled Linux manifest before executable discovery, even when payload is missing', () => {
    expect(
      packagedLinuxManifest({ isPackaged: true, platform: 'linux', resourcesPath: '/opt/ZeusAgent/resources' })
    ).toBe('/opt/ZeusAgent/resources/backend/runtime-manifest.json')
    expect(packagedLinuxManifest({ isPackaged: false, platform: 'linux', resourcesPath: '/resources' })).toBeNull()
    expect(packagedLinuxManifest({ isPackaged: true, platform: 'win32', resourcesPath: '/resources' })).toBeNull()
  })

  it('loads the shipped helper through a file URL and uses the exact private interpreter/environment', async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), 'Zeus Linux payload çığ '))

    try {
      await writeFile(
        path.join(directory, 'linux-runtime.mjs'),
        `export async function readCachedLinuxRuntime() { return ${JSON.stringify(runtime)}; }\nexport async function ensureLinuxRuntime() { throw new Error('must not install a cached runtime'); }\n`
      )
      const controller = createPackagedLinuxRuntime({ manifestPath: path.join(directory, 'runtime-manifest.json') })
      const cached = await controller.readCached()
      expect(cached).toEqual(runtime)
      expect(await controller.ensure()).toBe(cached)
      const backend = buildPackagedLinuxBackend(cached!, ['--profile', 'work', 'serve'], '/home/user/.zeus')
      expect(backend.command).toBe(runtime.python)
      expect(backend.args).toEqual(['-m', 'zeus_cli.main', '--profile', 'work', 'serve'])
      expect(backend.env.PYTHONPATH).toBe(runtime.root)
      expect(backend.env.ZEUS_HOME).toBe('/home/user/.zeus')
      expect(backend.env.PATH).toContain('/private/node/bin:/usr/bin')
      expect(backend.env.ZEUS_NODE).toBe(runtime.env.ZEUS_NODE)
      expect(backend.env.ZEUS_TUI_DIR).toBe(runtime.env.ZEUS_TUI_DIR)
      expect(backend.shell).toBe(false)
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  })

  it('keeps local provisioning behind the setup choice and never reads it for a remote connection', async () => {
    const module = { readCachedLinuxRuntime: vi.fn(async () => null), ensureLinuxRuntime: vi.fn(async () => runtime) }

    const controller = createPackagedLinuxRuntime({
      manifestPath: '/payload/runtime-manifest.json',
      loadModule: async () => module
    })

    const backend = { kind: 'bootstrap-needed', bundledManifest: '/payload/runtime-manifest.json' }
    let allowLocal!: (value: 'continue-local') => void

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
    expect(module.readCachedLinuxRuntime).not.toHaveBeenCalled()
    options.resolveRemote.mockResolvedValue(null)
    const pending = runPrimaryBackendStartup(options)
    await vi.waitFor(() => expect(options.waitForDecision).toHaveBeenCalled())
    expect(module.ensureLinuxRuntime).not.toHaveBeenCalled()
    allowLocal('continue-local')
    expect((await pending).kind).toBe('local')
    expect(module.ensureLinuxRuntime).toHaveBeenCalledTimes(1)
  })

  it('forwards cancellation and keeps failures latched until an explicit retry', async () => {
    const abort = new AbortController()

    const module = {
      readCachedLinuxRuntime: vi.fn(async () => null),
      ensureLinuxRuntime: vi.fn(async ({ signal }) => {
        abort.abort()
        signal.throwIfAborted()

        return runtime
      })
    }

    const controller = createPackagedLinuxRuntime({
      manifestPath: '/payload/runtime-manifest.json',
      loadModule: async () => module
    })

    await expect(controller.ensure({ signal: abort.signal })).rejects.toMatchObject({ bootstrapCancelled: true })
    await expect(controller.ensure()).rejects.toThrow('cancelled')
    expect(module.ensureLinuxRuntime).toHaveBeenCalledTimes(1)
    expect(controller.peek()).toBeNull()
    controller.reset()
    module.ensureLinuxRuntime.mockResolvedValue(runtime)
    expect(await controller.ensure()).toEqual(runtime)
  })
})
