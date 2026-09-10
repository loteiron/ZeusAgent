// Acceptance uses the installed binary and private bundled backend. No fake boot,
// source/Python overrides, inference request, or provider credentials are used.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';

assert.equal(process.platform, 'linux');
const output = path.resolve(process.env.ZEUS_ACCEPTANCE_OUTPUT);
const require = createRequire(path.join(process.env.ZEUS_ACCEPTANCE_DRIVER, 'package.json'));
const { _electron } = require('playwright');
const cwd = path.join(output, 'Project çığ 空間');
await fs.mkdir(cwd, { recursive: true });
const env = { ...process.env, PATH: '/usr/bin:/bin', ZEUS_HOME: path.join(output, 'state'),
  XDG_DATA_HOME: path.join(output, 'data'), ZEUS_DESKTOP_USER_DATA_DIR: path.join(output, 'electron'),
  ZEUS_DESKTOP_APP_NAME: 'ZeusAgentUbuntuAcceptance', ZEUS_DESKTOP_SKIP_QUIT_CONFIRM: '1' };
for (const key of Object.keys(env)) {
  if (/^(?:UV_|GITHUB_|GH_|OPENAI_|ANTHROPIC_|OPENROUTER_)/.test(key)
      || ['ZEUS_DESKTOP_ZEUS_ROOT', 'ZEUS_DESKTOP_PYTHON', 'ZEUS_PYTHON', 'ZEUS_NODE', 'VIRTUAL_ENV',
        'PYTHONPATH', 'PYTHONHOME', 'ELECTRON_RUN_AS_NODE', 'ZEUS_DESKTOP_RESOURCES',
        'ZEUS_DESKTOP_BOOT_FAKE', 'ZEUS_DESKTOP_DEV_SERVER'].includes(key)) delete env[key];
}
async function command(label, args, expected = 0) {
  const chunks = [];
  let failure;
  const code = await new Promise(resolve => {
    const child = spawn('/usr/bin/zeus', args, { cwd, env, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let force;
    const stop = signal => {
      try { process.kill(-child.pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; }
    };
    const deadline = setTimeout(() => {
      failure = new Error(`${label} timed out`);
      stop('SIGTERM');
      force = setTimeout(() => stop('SIGKILL'), 8000);
    }, 25 * 60_000);
    for (const stream of [child.stdout, child.stderr]) stream.on('data', data => { chunks.push(data); process.stdout.write(data); });
    child.on('error', error => { failure = error; });
    child.on('close', code => { clearTimeout(deadline); clearTimeout(force); resolve(code); });
  });
  const text = Buffer.concat(chunks).toString('utf8');
  await fs.writeFile(path.join(output, `${label}.log`), text);
  if (failure) throw failure;
  assert.equal(code, expected, `${label} exit code`);
  return text;
}

const before = Date.now();
const desktopFirst = process.env.ZEUS_ACCEPTANCE_FIRST === 'desktop';
async function probeCli() {
  assert.match(await command('cli-version', ['--version']), /0\.22\.0/);
  await command('cli-help', ['--help']);
  const detection = await command('cli-project-directory', ['verify', '--detect-only', '--json'], 1);
  const noRecipe = detection.split('\n').map(line => { try { return JSON.parse(line); } catch { return null; } }).find(row => row?.error === 'no-recipe');
  assert.equal(noRecipe?.root, cwd, 'Launcher must retain a caller directory containing spaces and Unicode');
  assert.match(await command('cli-update-plan', ['update', '--plan']), /zeus-linux-release/);
}
await fs.mkdir(env.ZEUS_HOME, { recursive: true });
await fs.writeFile(path.join(env.ZEUS_HOME, 'preserved.txt'), 'keep this through package upgrade and removal\n');
const runtimeDirectory = path.join(env.XDG_DATA_HOME, 'ZeusAgent', 'runtimes');
let readyPath, readyBefore;
async function captureRuntime() {
  const names = await fs.readdir(runtimeDirectory);
  assert.equal(names.length, 1);
  readyPath = path.join(runtimeDirectory, names[0], 'ready.json');
  readyBefore = await fs.readFile(readyPath, 'utf8');
  assert.equal(JSON.parse(readyBefore).commit, manifest.commit);
}
const stamp = JSON.parse(await fs.readFile('/opt/ZeusAgent/resources/install-stamp.json', 'utf8'));
const manifest = JSON.parse(await fs.readFile('/opt/ZeusAgent/resources/backend/runtime-manifest.json', 'utf8'));
assert.equal(stamp.dirty, false);
assert.equal(stamp.commit, manifest.commit);
assert.equal(stamp.commit, process.env.GITHUB_SHA);
if (!desktopFirst) {
  await probeCli();
  await captureRuntime();
}

const app = await _electron.launch({ executablePath: '/opt/ZeusAgent/ZeusAgent',
  args: ['--disable-gpu'], cwd, env, timeout: 25 * 60_000 });
let identity, connection;
try {
  const page = await app.firstWindow();
  page.setDefaultTimeout(180_000);
  await page.waitForFunction(() => Boolean(window.zeusDesktop?.getConnection));
  // Desktop-first exercises the real install overlay and asynchronous bootstrap.
  await page.waitForFunction(async () => {
    const value = await window.zeusDesktop.getConnection();
    return Boolean(value.baseUrl && value.token);
  }, undefined, { timeout: 25 * 60_000 });
  connection = await page.evaluate(async () => {
    const value = await window.zeusDesktop.getConnection();
    return { mode: value.mode, source: value.source, hasUrl: Boolean(value.baseUrl), hasToken: Boolean(value.token) };
  });
  assert.ok(connection.hasUrl && connection.hasToken, 'Installed Desktop must start its real authenticated backend');
  identity = await app.evaluate(({ app }) => ({ packaged: app.isPackaged, version: app.getVersion(), path: app.getAppPath() }));
  assert.ok(identity.packaged);
  assert.equal(identity.version, manifest.version);
  assert.ok(identity.path.startsWith('/opt/ZeusAgent/'));
  const later = page.getByRole('button', { name: "I'll choose a provider later" });
  await Promise.race([later.waitFor({ state: 'visible' }), page.locator('textarea, [contenteditable="true"]').first().waitFor({ state: 'visible' })]);
  if (await later.isVisible()) await later.click();
  await page.locator('textarea, [contenteditable="true"]').first().waitFor({ state: 'visible' });
  await page.waitForFunction(() => !/Starting ZeusAgent|Gateway\s+checking/i.test(document.body.innerText));
  await page.waitForFunction(() => {
    let element = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
    while (element) {
      const bounds = element.getBoundingClientRect();
      if (getComputedStyle(element).position === 'fixed' && bounds.left <= 0 && bounds.top <= 0
          && bounds.right >= innerWidth && bounds.bottom >= innerHeight) return false;
      element = element.parentElement;
    }
    return true;
  });
  await page.screenshot({ path: path.join(output, 'ZeusAgent-Ubuntu-Desktop.png'), animations: 'disabled' });
} catch (error) {
  await app.windows()[0]?.screenshot({ path: path.join(output, 'ZeusAgent-Ubuntu-failure.png'), animations: 'disabled' }).catch(() => {});
  throw error;
} finally {
  await app.close();
}
if (desktopFirst) {
  await captureRuntime();
  await probeCli();
}
assert.equal(await fs.readFile(readyPath, 'utf8'), readyBefore, 'The second interface must reuse the first runtime without provisioning again');
await fs.writeFile(path.join(output, 'acceptance.json'), JSON.stringify({
  platform: process.platform, arch: process.arch, os: (await fs.readFile('/etc/os-release', 'utf8')),
  commit: stamp.commit, identity, connection, callerDirectoryPreserved: true,
  exitStatusPreserved: true, coldBootstrap: true, firstInterface: desktopFirst ? 'desktop' : 'cli', sharedRuntimeReused: true,
  inferenceRequested: false, elapsedMs: Date.now() - before,
}, null, 2));
console.log('PASS: Ubuntu package cold CLI, real Desktop and shared private runtime');
