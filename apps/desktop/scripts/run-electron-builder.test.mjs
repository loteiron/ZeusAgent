import { spawnSync } from 'node:child_process'
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const here = path.dirname(fileURLToPath(import.meta.url))
const { expandMacro } = require('app-builder-lib/out/util/macroExpander')

describe('electron-builder invocation contract', () => {
  it.each([
    [[], 'never'],
    [['--publish', 'never'], 'never'],
    [['--publish=never'], 'never'],
    [['-p', 'never'], 'never'],
    [['--publish', 'onTag'], 'onTag'],
  ])('transports one effective publish policy for %j', async (publishArgs, expected) => {
    const fixture = await mkdtemp(path.join(os.tmpdir(), 'zeus-builder-policy-'))
    try {
      const builder = path.join(fixture, 'node_modules', 'electron-builder')
      await mkdir(builder, { recursive: true })
      await cp(path.join(here, 'run-electron-builder.mjs'), path.join(fixture, 'run.mjs'))
      await writeFile(path.join(builder, 'package.json'), JSON.stringify({ name: 'electron-builder', bin: 'observe.cjs' }))
      // Exercise the real wrapper subprocess and installed builder's parser,
      // without building an app or allowing a publisher to contact a service.
      await writeFile(path.join(builder, 'observe.cjs'), `
        const { createYargs, configureBuildCommand } = require(${JSON.stringify(require.resolve('electron-builder/out/builder'))});
        const parsed = configureBuildCommand(createYargs()).parse(process.argv.slice(2));
        console.log(JSON.stringify({ publish: parsed.publish, linux: parsed.linux, x64: parsed.x64 }));
      `)
      const result = spawnSync(process.execPath, [path.join(fixture, 'run.mjs'), '--linux', 'deb', '--x64', ...publishArgs], {
        encoding: 'utf8', timeout: 15_000,
      })
      expect(result.error).toBeUndefined()
      expect(result.status, result.stderr).toBe(0)
      expect(JSON.parse(result.stdout)).toEqual({ publish: expected, linux: ['deb'], x64: true })
    } finally {
      await rm(fixture, { recursive: true, force: true })
    }
  }, 20_000)

  it('keeps the advertised x64 deb filename when FPM expands Debian amd64 architecture', async () => {
    const metadata = JSON.parse(await readFile(path.join(here, '..', 'package.json'), 'utf8'))
    const pattern = metadata.build.deb.artifactName ?? metadata.build.artifactName
    const actual = expandMacro(pattern, 'amd64', { version: metadata.version }, { os: 'linux', ext: 'deb' })
    expect(actual).toBe(`ZeusAgent-${metadata.version}-linux-x64.deb`)
  })
})
