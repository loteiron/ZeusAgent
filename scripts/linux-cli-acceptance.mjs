#!/usr/bin/env node
// Native release acceptance: use the actual candidate archive, never a test stub.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync } from 'node:fs';
import { mkdtemp, mkdir, readFile, writeFile, copyFile, access, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { stageLinuxInstaller } from './stage_zeus_npm.mjs';

const options = {};
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  if (!['--package', '--assets', '--manifest', '--output'].includes(key) || !process.argv[index + 1] || options[key]) throw new Error('Usage: node scripts/linux-cli-acceptance.mjs --package candidate.tgz --assets downloaded-assets --manifest linux.json --output receipt.json');
  options[key] = path.resolve(process.argv[index + 1]);
}
assert.equal(Object.keys(options).length, 4);
assert.equal(process.platform, 'linux', 'Acceptance must run on native Linux');
assert.notEqual(process.getuid(), 0, 'Acceptance must run as an ordinary user');
const scratch = await mkdtemp(path.join(tmpdir(), 'zeus-cli-acceptance-'));
const log = `${options['--output']}.log`;
const manifest = JSON.parse(await readFile(options['--manifest'], 'utf8'));
const receipt = { version: manifest.version, commit: manifest.commit, package_sha256: createHash('sha256').update(await readFile(options['--package'])).digest('hex'), scratch, checks: [] };
// Candidate execution gets only OS lookup/locale context. In particular, no
// checkout/runtime overrides, GitHub token, provider key or Node/Python hooks
// can supply an alternate backend or authenticate an accidental network call.
const baseEnvironment = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  ['PATH', 'LANG', 'TERM', 'COLORTERM', 'TZ', 'TMPDIR'].includes(key) || /^LC_[A-Z_]+$/.test(key)));
async function run(command, args, { cwd = scratch, env = process.env, expected = 0 } = {}) {
  appendFileSync(log, `\nRunning ${JSON.stringify([command, ...args])}\n`);
  const child = spawn(command, args, { cwd, env, detached: true, stdio: ['ignore', 'pipe', 'pipe'], shell: false });
  let stdout = '', stderr = '', timedOut = false;
  const stop = signal => { try { process.kill(-child.pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; } };
  let force;
  const timeout = setTimeout(() => { timedOut = true; stop('SIGTERM'); force = setTimeout(() => stop('SIGKILL'), 5000); }, 30 * 60 * 1000);
  child.stdout.on('data', chunk => { appendFileSync(log, chunk); stdout = (stdout + chunk).slice(-1024 * 1024); });
  child.stderr.on('data', chunk => { appendFileSync(log, chunk); stderr = (stderr + chunk).slice(-1024 * 1024); });
  try {
    const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
    assert.ok(!timedOut, `Command timed out: ${command}; see ${log}`);
    if (expected !== null) assert.equal(code, expected, `${command}: ${stdout}\n${stderr}`);
    return { code, stdout, stderr };
  } finally { clearTimeout(timeout); clearTimeout(force); }
}
async function context(name) {
  const home = path.join(scratch, `${name} home Türkçe`);
  const project = path.join(scratch, `${name} caller project`);
  await mkdir(home); await mkdir(project);
  const env = { ...baseEnvironment, HOME: home, ZEUS_HOME: path.join(home, '.zeus'), XDG_DATA_HOME: path.join(home, '.local/share'), XDG_CACHE_HOME: path.join(home, '.cache') };
  await run('git', ['init', '--quiet'], { cwd: project, env });
  await writeFile(path.join(project, 'caller.txt'), 'release acceptance workspace\n');
  await run('git', ['add', 'caller.txt'], { cwd: project, env });
  await run('git', ['-c', 'user.name=Release Acceptance', '-c', 'user.email=acceptance@example.invalid', 'commit', '--quiet', '-m', 'fixture'], { cwd: project, env });
  return { home, project, env };
}
async function probe(command, ctx, label) {
  console.log(`[Zeus acceptance] ${label}: cold runtime/bootstrap`);
  const version = await run(command, ['--version'], { cwd: ctx.project, env: ctx.env });
  assert.ok(version.stdout.includes(manifest.version), 'Installed version must match manifest');
  const status = await run(command, ['verify', '--status', '--json'], { cwd: ctx.project, env: ctx.env, expected: null });
  const observed = JSON.parse(status.stdout.trim()).verification;
  assert.equal(await realpath(observed.workspace.root), await realpath(ctx.project), 'Installed command must inspect the original caller workspace');
  assert.equal(status.code, 1, 'A fresh workspace has no recorded checks');
  receipt.checks.push({ surface: label, version: version.stdout.trim(), workspace: observed.workspace.root, status: observed.status, passed: true });
}
let npm;
for (const candidate of [process.env.npm_execpath, path.join(path.dirname(process.execPath), '../lib/node_modules/npm/bin/npm-cli.js'), '/usr/share/nodejs/npm/bin/npm-cli.js'].filter(Boolean)) {
  try { await access(candidate); npm = candidate; break; } catch {}
}
assert.ok(npm, 'Acceptance Node installation must include npm');
const npmCtx = await context('npm');
const prefix = path.join(npmCtx.home, 'global');
await run(process.execPath, [npm, 'install', '--global', '--prefix', prefix, '--ignore-scripts', '--no-audit', '--no-fund', options['--package']], { env: npmCtx.env });
const installed = path.join(prefix, 'lib/node_modules/@loteiron/zeus-agent');
assert.deepEqual(JSON.parse(await readFile(path.join(installed, 'linux-runtime-manifest.json'), 'utf8')), manifest);
for (const asset of [manifest.source, manifest.uv, ...Object.values(manifest.tools)]) {
  assert.match(asset.file, /^[A-Za-z0-9_.-]+$/);
  await copyFile(path.join(options['--assets'], asset.file), path.join(installed, asset.file));
}
await probe(path.join(prefix, 'bin/zeus'), npmCtx, 'npm global');
const standalone = await context('standalone');
const assets = path.join(scratch, 'standalone assets');
await mkdir(assets);
for (const asset of [manifest.source, manifest.uv, ...Object.values(manifest.tools)]) await copyFile(path.join(options['--assets'], asset.file), path.join(assets, asset.file));
await copyFile(options['--package'], path.join(assets, path.basename(options['--package'])));
const installer = path.join(scratch, 'install-linux.sh');
await stageLinuxInstaller({ packagePath: options['--package'], linuxManifestPath: options['--manifest'], outputPath: installer });
console.log('[Zeus acceptance] standalone: private Node and cold runtime/bootstrap');
await run('bash', [installer, '--assets', assets], { cwd: standalone.project, env: standalone.env });
await probe(path.join(standalone.home, '.local/bin/zeus'), standalone, 'standalone user command');
receipt.completed_at = new Date().toISOString();
await writeFile(options['--output'], JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt, null, 2));
