import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { buildDesktopBackendEnv } from './backend-env'
import { createPackagedRuntime, type PackagedRuntime as Runtime, type RuntimeOptions } from './packaged-runtime'

type RuntimeModule = {
  readCachedWindowsRuntime: (options: { manifestPath: string }) => Promise<Runtime | null>
  ensureWindowsRuntime: (options: RuntimeOptions) => Promise<Runtime>
}

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

export function createPackagedWindowsRuntime({
  manifestPath,
  loadModule = loadRuntimeModule
}: {
  manifestPath: string
  loadModule?: (manifestPath: string) => Promise<RuntimeModule>
}) {
  return createPackagedRuntime({
    manifestPath,
    loadModule: async file => {
      const module = await loadModule(file)

      return { readCachedRuntime: module.readCachedWindowsRuntime, ensureRuntime: module.ensureWindowsRuntime }
    }
  })
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
