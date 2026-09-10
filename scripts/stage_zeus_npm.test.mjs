import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile, cp, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { randomUUID } from 'node:crypto';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const stager = path.join(root, 'scripts/stage_zeus_npm.mjs');
const npmCandidates = [
  process.env.npm_execpath,
  path.join(path.dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js'),
  path.join(path.dirname(process.execPath), '../lib/node_modules/npm/bin/npm-cli.js'),
].filter(Boolean);

async function npmCli() {
  for (const candidate of npmCandidates) {
    try { await access(candidate); return candidate; } catch {}
  }
  throw new Error('Run this test using a Node installation that includes npm.');
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', timeout: 60_000, ...options });
  assert.ifError(result.error);
  return result;
}

function succeeded(result) {
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result;
}

test('npm pack and global install expose a relocatable Windows command in both shells', {
  skip: process.platform !== 'win32', timeout: 120_000,
}, async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus npm Türkçe '));
  const fixture = path.join(scratch, 'release source');
  await mkdir(path.join(fixture, 'scripts'), { recursive: true });
  await cp(path.join(root, 'packages/zeus-cli'), path.join(fixture, 'packages/zeus-cli'), { recursive: true });
  await cp(stager, path.join(fixture, 'scripts/stage_zeus_npm.mjs'));
  await cp(path.join(root, 'LICENSE'), path.join(fixture, 'LICENSE'));
  // Real npm shims launch this stand-in for the separately tested runtime bootstrap.
  // It makes CWD, argument transport and exit-code loss observable without a network.
  await writeFile(path.join(fixture, 'scripts/windows-runtime.mjs'), `
    console.log(JSON.stringify({argv: process.argv.slice(2), cwd: process.cwd()}));
    process.exitCode = 23;
  `);
  const manifest = path.join(scratch, 'release manifest.json');
  await writeFile(manifest, JSON.stringify({ version: '1.2.3', source: { url: 'https://example.invalid/source.zip' } }));
  const staging = path.join(scratch, 'npm package');
  succeeded(run(process.execPath, [path.join(fixture, 'scripts/stage_zeus_npm.mjs'), '--manifest', manifest, '--output', staging]));
  // A private sibling and ordinary editor debris must never enter the tarball.
  await writeFile(path.join(staging, '.env'), 'PRIVATE_FIXTURE=not-a-real-secret');
  await writeFile(path.join(staging, 'unrelated.txt'), 'do not ship');
  const npm = await npmCli();
  const packed = JSON.parse(succeeded(run(process.execPath, [npm, 'pack', '--json', '--ignore-scripts'], { cwd: staging })).stdout)[0];
  assert.deepEqual(packed.files.map(item => item.path).sort(), [
    'LICENSE', 'README.md', 'bin/zeus.mjs', 'lib/windows-runtime.mjs', 'package.json', 'runtime-manifest.json',
  ]);
  const tarball = path.join(staging, packed.filename);
  const prefix = path.join(scratch, 'global prefix');
  succeeded(run(process.execPath, [npm, 'install', '--global', '--prefix', prefix, '--ignore-scripts', '--no-audit', '--no-fund', tarball], { cwd: scratch }));
  const installed = path.join(prefix, 'node_modules/@loteiron/zeus-agent');
  const metadata = JSON.parse(await readFile(path.join(installed, 'package.json'), 'utf8'));
  assert.equal(metadata.version, '1.2.3');
  assert.equal(metadata.bin.zeus, 'bin/zeus.mjs');
  assert.equal(metadata.scripts, undefined, 'installation must not execute lifecycle scripts');

  const project = path.join(scratch, 'caller project Türkçe');
  await mkdir(project);
  const env = { ...process.env, PATH: `${prefix}${path.delimiter}${process.env.PATH}` };
  // CMD itself is the surface under test. The command text is a fixed literal.
  const cmd = run(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', 'zeus --probe'], { cwd: project, env });
  assert.equal(cmd.status, 23, cmd.stderr);
  const observedCmd = JSON.parse(cmd.stdout.trim());
  assert.equal(observedCmd.cwd, project);
  assert.deepEqual(observedCmd.argv, ['--manifest', path.join(installed, 'runtime-manifest.json'), '--', '--probe']);

  const psScript = path.join(scratch, 'invoke.ps1');
  // Windows PowerShell 5.1 needs a BOM to interpret a UTF-8 script as Unicode.
  await writeFile(psScript, "\uFEFF& zeus --query 'Türkçe boşluk & $ literal' '--desktop'\nexit $LASTEXITCODE\n");
  const ps = run('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', psScript], { cwd: project, env });
  assert.equal(ps.status, 23, ps.stderr);
  const observedPs = JSON.parse(ps.stdout.trim());
  assert.equal(observedPs.cwd, project);
  assert.deepEqual(observedPs.argv, ['--manifest', path.join(installed, 'runtime-manifest.json'), '--', '--query', 'Türkçe boşluk & $ literal', '--desktop']);
});

test('staging refuses to overwrite an existing output directory', async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus npm existing '));
  const manifest = path.join(scratch, 'manifest.json');
  await writeFile(manifest, JSON.stringify({ version: '1.2.3' }));
  const output = path.join(scratch, 'existing');
  await mkdir(output);
  await writeFile(path.join(output, 'user.txt'), 'preserve this');
  const result = run(process.execPath, [stager, '--manifest', manifest, '--output', output]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /already exists/i);
  assert.equal(await readFile(path.join(output, 'user.txt'), 'utf8'), 'preserve this');
});

test('desktop launch uses its registered Unicode installation without bootstrapping Python', {
  skip: process.platform !== 'win32', timeout: 30_000,
}, async () => {
  const { launchDesktop } = await import('../packages/zeus-cli/bin/zeus.mjs');
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus desktop Türkçe '));
  const installed = path.join(scratch, 'installed app');
  await mkdir(installed);
  // A real PE executable observes the actual native process argv/environment.
  await cp(process.execPath, path.join(installed, 'ZeusAgent.exe'));
  const observer = path.join(scratch, 'observe.mjs');
  const output = path.join(scratch, 'observed.json');
  await writeFile(observer, `import {writeFileSync} from 'node:fs';
    writeFileSync(process.argv[2], JSON.stringify({cwd: process.cwd(), args: process.argv.slice(3),
      mode: process.env.ELECTRON_RUN_AS_NODE ?? null, resources: process.env.ZEUS_DESKTOP_RESOURCES ?? null}));
    process.exitCode = 17;`);
  const key = `HKCU\\Software\\ZeusAgentTest\\Npm-${randomUUID()}`;
  const oldMode = process.env.ELECTRON_RUN_AS_NODE;
  const oldResources = process.env.ZEUS_DESKTOP_RESOURCES;
  try {
    succeeded(run('reg.exe', ['add', key, '/v', 'InstallDirectory', '/t', 'REG_SZ', '/d', installed, '/f']));
    process.env.ELECTRON_RUN_AS_NODE = '1';
    process.env.ZEUS_DESKTOP_RESOURCES = 'stale resources';
    assert.equal(await launchDesktop([observer, output, 'Türkçe & $ literal'], key), 17);
    assert.deepEqual(JSON.parse(await readFile(output, 'utf8')), {
      cwd: process.cwd(), args: ['Türkçe & $ literal'], mode: null, resources: null,
    });
  } finally {
    run('reg.exe', ['delete', key, '/f']);
    if (oldMode === undefined) delete process.env.ELECTRON_RUN_AS_NODE; else process.env.ELECTRON_RUN_AS_NODE = oldMode;
    if (oldResources === undefined) delete process.env.ZEUS_DESKTOP_RESOURCES; else process.env.ZEUS_DESKTOP_RESOURCES = oldResources;
  }
  await assert.rejects(() => launchDesktop([], key), /install.*desktop/i);
});
