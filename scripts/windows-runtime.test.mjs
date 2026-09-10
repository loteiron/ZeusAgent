import assert from 'node:assert/strict';
import { mkdtemp, writeFile, mkdir, readFile, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { ensureWindowsRuntime, readCachedWindowsRuntime, recoverManagedPython } from './windows-runtime.mjs';

const digest = value => createHash('sha256').update(value).digest('hex');
const powershell = path.join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
async function sourceZip(f, names = ['zeus-agent/zeus']) {
  const target = path.join(f.dir, 'source.zip');
  const script = `
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::Open($env:ZIP_TARGET, [IO.Compression.ZipArchiveMode]::Create)
    try { foreach ($name in (ConvertFrom-Json $env:ZIP_NAMES)) {
      $entry = $zip.CreateEntry($name)
      $stream = [IO.StreamWriter]::new($entry.Open())
      try { $stream.Write('fixture source') } finally { $stream.Dispose() }
    } } finally { $zip.Dispose() }
  `;
  execFileSync(powershell, ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], {
    env: { ...process.env, ZIP_TARGET: target, ZIP_NAMES: JSON.stringify(names) }, windowsHide: true,
  });
  f.manifest.source.sha256 = digest(await readFile(target));
  await f.save();
}

function runtimeDir(f) { return path.join(f.runtimeBaseDir, `${f.manifest.version}-${f.manifest.source.sha256.slice(0, 12)}`); }
async function fixture(t) {
  const dir = await mkdtemp(path.join(tmpdir(), 'zeus-runtime-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const manifest = {
    schemaVersion: 1, version: '0.22.0', commit: 'a'.repeat(40), python: '3.12.12',
    source: { file: 'source.zip', sha256: digest('reviewed source'), root: 'zeus-agent' },
    uv: { file: 'uv.zip', sha256: digest('reviewed uv'), executable: 'uv.exe' },
  };
  const manifestPath = path.join(dir, 'runtime-manifest.json');
  const save = () => writeFile(manifestPath, JSON.stringify(manifest));
  await save();
  return { dir, manifest, manifestPath, save, runtimeBaseDir: path.join(dir, 'runtime') };
}

test('a tampered payload is rejected before extraction or execution', async t => {
  const f = await fixture(t);
  await writeFile(path.join(f.dir, 'source.zip'), 'changed source');
  await assert.rejects(ensureWindowsRuntime(f), /checksum/i);
});

test('manifest paths cannot escape their owned extraction root', async t => {
  const f = await fixture(t);
  f.manifest.source.root = '../outside';
  await f.save();
  await assert.rejects(ensureWindowsRuntime(f), /relative|path|root/i);
});

test('downloads never allow insecure or credential-bearing URLs', async t => {
  const f = await fixture(t);
  for (const url of ['http://example.com/source.zip', 'https://secret:token@example.com/source.zip']) {
    f.manifest.source.url = url;
    await f.save();
    await assert.rejects(ensureWindowsRuntime(f), /HTTPS|credential/i);
  }
});

test('an aborted request creates no runtime', async t => {
  const f = await fixture(t);
  await assert.rejects(ensureWindowsRuntime({ ...f, signal: AbortSignal.abort() }), /abort/i);
});

test('missing local payload has an actionable error without a release URL', async t => {
  const f = await fixture(t);
  await assert.rejects(ensureWindowsRuntime(f), /source.zip.*missing|missing.*source.zip/i);
});

test('invalid manifest cannot be treated as a ready installation', async t => {
  const f = await fixture(t);
  f.manifest.python = 'latest';
  await f.save();
  await assert.rejects(ensureWindowsRuntime(f), /Python|python/i);
});

test('actual ZIP traversal is rejected before even the safe entries are published', async t => {
  const f = await fixture(t);
  await sourceZip(f, ['zeus-agent/zeus', '../outside.txt']);
  await assert.rejects(ensureWindowsRuntime(f), /Unsafe archive entry/);
  await assert.rejects(readFile(path.join(runtimeDir(f), 'source', 'zeus-agent', 'zeus')), { code: 'ENOENT' });
  await assert.rejects(readFile(path.join(runtimeDir(f), 'outside.txt')), { code: 'ENOENT' });
});

test('real extraction publishes once across concurrent bootstrap requests and retries', async t => {
  const f = await fixture(t);
  await sourceZip(f);
  await writeFile(path.join(f.dir, 'uv.zip'), 'tampered uv');
  const events = [];
  const requests = await Promise.allSettled([1, 2].map(() => ensureWindowsRuntime({ ...f, onProgress: e => events.push(e) })));
  assert.ok(requests.every(r => r.status === 'rejected' && /checksum/.test(r.reason.message)));
  assert.equal(await readFile(path.join(runtimeDir(f), 'source', 'zeus-agent', 'zeus'), 'utf8'), 'fixture source');
  assert.equal(events.filter(e => e.message === 'Preparing source').length, 1);
  await assert.rejects(readFile(path.join(runtimeDir(f), 'ready.json')), { code: 'ENOENT' });
  await assert.rejects(readFile(path.join(runtimeDir(f), 'bootstrap.lock', 'owner.json')), { code: 'ENOENT' });
});

test('a waiter can cancel without removing another process-owned lock', async t => {
  const f = await fixture(t);
  const lock = path.join(runtimeDir(f), 'bootstrap.lock');
  await mkdir(lock, { recursive: true });
  const owner = JSON.stringify({ pid: process.pid, token: 'belongs-to-running-owner' });
  await writeFile(path.join(lock, 'owner.json'), owner);
  await assert.rejects(ensureWindowsRuntime({ ...f, signal: AbortSignal.timeout(80) }), /abort/i);
  assert.equal(await readFile(path.join(lock, 'owner.json'), 'utf8'), owner);
});

test('cached resolver is read-only and retains caller configuration and workspace', async t => {
  const f = await fixture(t);
  assert.equal(await readCachedWindowsRuntime(f), null);
  await assert.rejects(readFile(path.join(runtimeDir(f), 'ready.json')), { code: 'ENOENT' });
  const root = path.join(runtimeDir(f), 'source', 'zeus-agent');
  await mkdir(path.join(root, '.venv', 'Scripts'), { recursive: true });
  await writeFile(path.join(root, 'zeus'), 'fixture source');
  await writeFile(path.join(root, '.venv', 'Scripts', 'python.exe'), 'fixture python');
  for (const file of ['ui-tui/dist/entry.js', 'zeus_cli/web_dist/index.html']) {
    await mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await writeFile(path.join(root, file), 'fixture built frontend');
  }
  await writeFile(path.join(runtimeDir(f), 'ready.json'), JSON.stringify({ manifestHash: digest(JSON.stringify(f.manifest)) }));
  const before = process.cwd();
  const cached = await readCachedWindowsRuntime(f);
  assert.equal(cached.root, root);
  assert.equal(cached.env.ZEUS_HOME, process.env.ZEUS_HOME);
  assert.equal(cached.env.ELECTRON_RUN_AS_NODE, undefined);
  assert.equal(cached.env.ZEUS_DESKTOP_RESOURCES, undefined);
  assert.equal(process.cwd(), before);
  assert.equal((await ensureWindowsRuntime(f)).python, cached.python);
  await rm(path.join(root, 'ui-tui', 'dist', 'entry.js'));
  await assert.rejects(readCachedWindowsRuntime(f), /incomplete/);
});

test('cached runtime is bound to the complete manifest, including Python and tools', async t => {
  const f = await fixture(t);
  await mkdir(runtimeDir(f), { recursive: true });
  await writeFile(path.join(runtimeDir(f), 'ready.json'), JSON.stringify({ manifestHash: digest(JSON.stringify(f.manifest)) }));
  f.manifest.python = '3.12.11';
  await f.save();
  await assert.rejects(readCachedWindowsRuntime(f), /different manifest/);
});

test('cancelling actual provisioning terminates its child process tree and leaves no ready marker', { timeout: 20000 }, async t => {
  const f = await fixture(t);
  await sourceZip(f);
  const uvFiles = path.join(f.dir, 'uv-files');
  await mkdir(uvFiles);
  const source = path.join(f.dir, 'uv-fixture.cs');
  await writeFile(source, `using System; using System.IO; using System.Diagnostics; using System.Threading;
    class Program { static void Main(string[] args) {
      if (args.Length > 0 && args[0] == "child") {
        File.WriteAllText("fixture-child.pid", Process.GetCurrentProcess().Id.ToString());
      } else {
        File.WriteAllText("fixture-parent.pid", Process.GetCurrentProcess().Id.ToString());
        Process.Start(new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName, "child") {
          UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Environment.CurrentDirectory });
      }
      Thread.Sleep(60000);
    } }`);
  execFileSync(path.join(process.env.SystemRoot, 'Microsoft.NET', 'Framework64', 'v4.0.30319', 'csc.exe'),
    ['/nologo', `/out:${path.join(uvFiles, 'uv.exe')}`, source], { windowsHide: true });
  const zipScript = `$ProgressPreference = 'SilentlyContinue'; Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::CreateFromDirectory($env:ZIP_FOLDER, $env:ZIP_TARGET)`;
  execFileSync(powershell, ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(zipScript, 'utf16le').toString('base64')], {
    env: { ...process.env, ZIP_FOLDER: uvFiles, ZIP_TARGET: path.join(f.dir, 'uv.zip') }, windowsHide: true,
  });
  f.manifest.uv.sha256 = digest(await readFile(path.join(f.dir, 'uv.zip')));
  await f.save();
  const controller = new AbortController();
  const run = ensureWindowsRuntime({ ...f, signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]) });
  // Attach immediately so a setup failure is observable without an unhandled rejection.
  const stopped = assert.rejects(run, /abort|timed out/i);
  const root = path.join(runtimeDir(f), 'source', 'zeus-agent');
  try {
    const started = Date.now();
    while (!await readFile(path.join(root, 'fixture-child.pid'), 'utf8').catch(() => null)) {
      assert.ok(Date.now() - started < 8000, 'provisioning child never started');
      await delay(30);
    }
    const pids = await Promise.all(['parent', 'child'].map(async name => Number(await readFile(path.join(root, `fixture-${name}.pid`), 'utf8'))));
    controller.abort();
    await stopped;
    for (const pid of pids) assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' });
    await assert.rejects(readFile(path.join(runtimeDir(f), 'ready.json')), { code: 'ENOENT' });
    await assert.rejects(readFile(path.join(runtimeDir(f), 'bootstrap.lock', 'owner.json')), { code: 'ENOENT' });
  } finally { controller.abort(); await stopped; }
});

test('Python alias recovery never swallows unrelated errors or an error about another runtime', async t => {
  const f = await fixture(t);
  const options = { pythonRoot: path.join(f.dir, 'python'), version: '3.12.12', env: process.env };
  for (const message of ['Download checksum failed',
    `Missing expected target directory for Python minor version link at ${path.join(f.dir, 'other-python')}`]) {
    const original = new Error(message);
    await assert.rejects(recoverManagedPython(original, options), error => error === original);
  }
});

test('Python alias recovery requires the exact native interpreter identity in its physical owned directory', async t => {
  const f = await fixture(t);
  const pythonRoot = path.join(f.dir, 'python');
  const patch = path.join(pythonRoot, 'cpython-3.12.12-windows-x86_64-none');
  await mkdir(patch, { recursive: true });
  const options = { pythonRoot, version: '3.12.12', env: process.env };
  const original = new Error(`uv.exe failed (2): error: Missing expected target directory for Python minor version link at ${patch}`);
  await assert.rejects(recoverManagedPython(original, options), /recovery refused/);
  const source = path.join(f.dir, 'identity-fixture.cs');
  for (const version of ['3.12.11', '3.12.12']) {
    const json = JSON.stringify({ version, implementation: 'cpython', bits: 64 }).replaceAll('"', '""');
    await writeFile(source, `using System; class Program { static void Main() { Console.WriteLine(@"${json}"); } }`);
    execFileSync(path.join(process.env.SystemRoot, 'Microsoft.NET', 'Framework64', 'v4.0.30319', 'csc.exe'),
      ['/nologo', `/out:${path.join(patch, 'python.exe')}`, source], { windowsHide: true });
    if (version === '3.12.11') await assert.rejects(recoverManagedPython(original, options), /does not match/);
    else assert.equal(await recoverManagedPython(original, options), await realpath(path.join(patch, 'python.exe')));
  }
});
