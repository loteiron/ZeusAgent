import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { buildDesktopBackendEnv } from './backend-env'
import { createPackagedRuntime, type PackagedRuntime, type RuntimeOptions } from './packaged-runtime'

type LinuxRuntimeModule = {
  readCachedLinuxRuntime: (options: { manifestPath: string }) => Promise<PackagedRuntime | null>
  ensureLinuxRuntime: (options: RuntimeOptions) => Promise<PackagedRuntime>
}

export function packagedLinuxManifest({
  isPackaged,
  platform,
  resourcesPath
}: {
  isPackaged: boolean
  platform: string
  resourcesPath: string
}) {
  // Never fall back to /usr/bin/zeus, which launches this same packaged app.
  return isPackaged && platform === 'linux' ? path.posix.join(resourcesPath, 'backend', 'runtime-manifest.json') : null
}

async function loadRuntimeModule(manifestPath: string): Promise<LinuxRuntimeModule> {
  const url = pathToFileURL(path.join(path.dirname(manifestPath), 'linux-runtime.mjs')).href

  return await import(/* @vite-ignore */ url)
}

export function createPackagedLinuxRuntime({
  manifestPath,
  loadModule = loadRuntimeModule
}: {
  manifestPath: string
  loadModule?: (manifestPath: string) => Promise<LinuxRuntimeModule>
}) {
  return createPackagedRuntime({
    manifestPath,
    loadModule: async file => {
      const module = await loadModule(file)

      return { readCachedRuntime: module.readCachedLinuxRuntime, ensureRuntime: module.ensureLinuxRuntime }
    }
  })
}

export function buildPackagedLinuxBackend(runtime: PackagedRuntime, backendArgs: string[], zeusHome: string) {
  return {
    kind: 'python',
    label: `ZeusAgent ${runtime.version} at ${runtime.root}`,
    command: runtime.python,
    args: ['-m', 'zeus_cli.main', ...backendArgs],
    env: {
      ...runtime.env,
      ...buildDesktopBackendEnv({
        zeusHome,
        pythonPathEntries: [runtime.root],
        venvRoot: runtime.venvRoot,
        currentEnv: runtime.env,
        platform: 'linux'
      })
    },
    root: runtime.root,
    bootstrap: false,
    shell: false
  }
}
