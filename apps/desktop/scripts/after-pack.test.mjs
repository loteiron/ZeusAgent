import { mkdtemp, mkdir, writeFile, readFile, stat, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import afterPack from './after-pack.mjs'

describe('Linux package CLI staging', () => {
  it('refuses to package a missing CLI launcher', async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), 'zeus-linux-package-'))
    try {
      await expect(afterPack({ electronPlatformName: 'linux', appOutDir: directory })).rejects.toMatchObject({ code: 'ENOENT' })
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  })

  it.skipIf(process.platform === 'win32')('makes only the staged copy executable before dpkg records permissions', async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), 'zeus-linux-package-'))
    try {
      const resourceDir = path.join(directory, 'resources', 'cli')
      const launcher = path.join(resourceDir, 'zeus')
      await mkdir(resourceDir, { recursive: true })
      await writeFile(launcher, '#!/bin/sh\nprintf "fixture\\n"\n', { mode: 0o644 })
      await afterPack({ electronPlatformName: 'linux', appOutDir: directory })
      expect((await stat(launcher)).mode & 0o777).toBe(0o755)
      expect(await readFile(launcher, 'utf8')).toBe('#!/bin/sh\nprintf "fixture\\n"\n')
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  })
})
