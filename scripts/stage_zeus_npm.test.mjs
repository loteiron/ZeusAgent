import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile, cp, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

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

function packedRelease(result) {
  // npm 12 keys pack JSON by package name; earlier supported npm emits a list.
  const value = JSON.parse(succeeded(result).stdout);
  const entries = Array.isArray(value) ? value : Object.values(value);
  assert.equal(entries.length, 1, 'Exactly one release package must be packed');
  const packed = entries[0];
  assert.equal(packed.name, '@loteiron/zeus-agent');
  assert.equal(typeof packed.filename, 'string');
  assert.ok(Array.isArray(packed.files));
  return packed;
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
  const packed = packedRelease(run(process.execPath, [npm, 'pack', '--json', '--ignore-scripts'], { cwd: staging }));
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
  const env = { ...process.env, PATH: [prefix, path.dirname(process.execPath), process.env.PATH].join(path.delimiter) };
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

test('one packed release contains both platform runtimes without install scripts', async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus universal npm '));
  const manifest = path.join(scratch, 'windows.json');
  const linuxManifest = path.join(scratch, 'linux.json');
  await writeFile(manifest, JSON.stringify({ version: '1.2.3', commit: 'a'.repeat(40) }));
  await writeFile(linuxManifest, JSON.stringify({ version: '1.2.3', commit: 'a'.repeat(40), platform: 'linux' }));
  const output = path.join(scratch, 'package');
  succeeded(run(process.execPath, [stager, '--manifest', manifest, '--linux-manifest', linuxManifest, '--output', output]));
  const npm = await npmCli();
  const packed = packedRelease(run(process.execPath, [npm, 'pack', '--json', '--ignore-scripts'], { cwd: output }));
  assert.deepEqual(packed.files.map(item => item.path).sort(), [
    'LICENSE', 'README.md', 'bin/zeus.mjs', 'lib/linux-runtime.mjs', 'lib/windows-runtime.mjs',
    'linux-runtime-manifest.json', 'package.json', 'runtime-manifest.json',
  ]);
  const metadata = JSON.parse(await readFile(path.join(output, 'package.json'), 'utf8'));
  assert.deepEqual(metadata.os, ['win32', 'linux']);
  assert.equal(metadata.scripts, undefined);
  assert.equal(JSON.parse(await readFile(path.join(output, 'linux-runtime-manifest.json'), 'utf8')).platform, 'linux');
});

test('universal staging rejects mismatched source identities before publishing files', async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus mixed release '));
  const manifest = path.join(scratch, 'windows.json');
  const linuxManifest = path.join(scratch, 'linux.json');
  await writeFile(manifest, JSON.stringify({ version: '1.2.3', commit: 'a'.repeat(40) }));
  await writeFile(linuxManifest, JSON.stringify({ version: '1.2.3', commit: 'b'.repeat(40) }));
  const output = path.join(scratch, 'package');
  const result = run(process.execPath, [stager, '--manifest', manifest, '--linux-manifest', linuxManifest, '--output', output]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /same.*(source|commit|release)/i);
  await assert.rejects(access(path.join(output, 'package.json')));
});

test('Linux global npm command preserves caller CWD, Unicode arguments and runtime exit status', {
  skip: process.platform !== 'linux', timeout: 120_000,
}, async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus npm Linux Türkçe '));
  const fixture = path.join(scratch, 'source');
  await mkdir(path.join(fixture, 'scripts'), { recursive: true });
  await cp(path.join(root, 'packages/zeus-cli'), path.join(fixture, 'packages/zeus-cli'), { recursive: true });
  await cp(stager, path.join(fixture, 'scripts/stage_zeus_npm.mjs'));
  await cp(path.join(root, 'LICENSE'), path.join(fixture, 'LICENSE'));
  await writeFile(path.join(fixture, 'scripts/windows-runtime.mjs'), 'throw new Error("wrong platform selected");');
  await writeFile(path.join(fixture, 'scripts/linux-runtime.mjs'), `console.log(JSON.stringify({argv: process.argv.slice(2), cwd: process.cwd()})); process.exitCode = 23;`);
  const manifest = path.join(scratch, 'manifest.json');
  await writeFile(manifest, JSON.stringify({ version: '1.2.3', commit: 'a'.repeat(40) }));
  const output = path.join(scratch, 'package');
  succeeded(run(process.execPath, [path.join(fixture, 'scripts/stage_zeus_npm.mjs'), '--manifest', manifest, '--linux-manifest', manifest, '--output', output]));
  const npm = await npmCli();
  const packed = packedRelease(run(process.execPath, [npm, 'pack', '--json', '--ignore-scripts'], { cwd: output }));
  const prefix = path.join(scratch, 'global prefix');
  succeeded(run(process.execPath, [npm, 'install', '--global', '--prefix', prefix, '--ignore-scripts', '--no-audit', '--no-fund', path.join(output, packed.filename)]));
  const project = path.join(scratch, 'caller project Türkçe');
  await mkdir(project);
  const result = run(path.join(prefix, 'bin/zeus'), ['--query', 'Türkçe & $ literal', '--desktop'], { cwd: project });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    cwd: project,
    argv: ['--manifest', path.join(prefix, 'lib/node_modules/@loteiron/zeus-agent/linux-runtime-manifest.json'), '--', '--query', 'Türkçe & $ literal', '--desktop'],
  });
});

test('Linux npm wrapper forwards service SIGTERM so its helper can stop its owned child', {
  skip: process.platform !== 'linux', timeout: 15_000,
}, async t => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus npm stop '));
  await mkdir(path.join(scratch, 'bin'));
  await mkdir(path.join(scratch, 'lib'));
  await cp(path.join(root, 'packages/zeus-cli/bin/zeus.mjs'), path.join(scratch, 'bin/zeus.mjs'));
  await writeFile(path.join(scratch, 'linux-runtime-manifest.json'), '{}');
  const witness = path.join(scratch, 'pids.json');
  await writeFile(path.join(scratch, 'lib/linux-runtime.mjs'), `
    import {spawn} from 'node:child_process';
    import {writeFileSync} from 'node:fs';
    const child = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)']);
    process.on('SIGTERM', () => { child.kill('SIGTERM'); });
    child.on('close', () => { process.exitCode = 143; });
    writeFileSync(process.env.ZEUS_NPM_STOP_WITNESS, JSON.stringify([process.pid, child.pid]));
  `);
  const wrapper = spawn(process.execPath, [path.join(scratch, 'bin/zeus.mjs')], {
    detached: true, stdio: 'ignore', env: { ...process.env, ZEUS_NPM_STOP_WITNESS: witness },
  });
  t.after(() => { try { process.kill(-wrapper.pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; } });
  const closed = new Promise((resolve, reject) => { wrapper.once('close', (code, signal) => resolve({ code, signal })); wrapper.once('error', reject); });
  let pids;
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline && !pids) {
    try { pids = JSON.parse(await readFile(witness, 'utf8')); } catch {}
    if (!pids) await delay(20);
  }
  assert.ok(pids, 'Real runtime helper and its child must start before interruption');
  wrapper.kill('SIGTERM');
  assert.deepEqual(await closed, { code: 143, signal: null }, 'Wrapper must wait for helper cleanup and preserve its exit status');
  for (const pid of pids) assert.throws(() => process.kill(pid, 0), error => error.code === 'ESRCH', 'Helper and owned child must both be gone');
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
