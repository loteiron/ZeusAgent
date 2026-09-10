#!/usr/bin/env node
// Shared by the Windows installer, Electron and the npm command. No system Python,
// Git or Node installation is needed when Electron supplies this JavaScript runtime.
import { createHash, randomUUID } from 'node:crypto';
import { createReadStream, createWriteStream } from 'node:fs';
import * as fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const MAX_ARCHIVE = 768 * 1024 * 1024;
const MAX_WAIT = 30 * 60 * 1000;
const HEX = /^[a-f0-9]{64}$/;
const FRONTENDS = ['ui-tui/dist/entry.js', 'zeus_cli/web_dist/index.html'];

function relative(value, label, single = false) {
  if (typeof value !== 'string' || !value || value.includes('\\') || value.includes(':')
      || value.startsWith('/') || value.split('/').some(p => !p || p === '.' || p === '..')
      || (single && value.includes('/')) || /[\x00-\x1f]/.test(value)) {
    throw new Error(`Invalid relative ${label} path`);
  }
  return value;
}

function validate(manifest) {
  if (manifest?.schemaVersion !== 1 || !/^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$/.test(manifest.version)
      || !/^[a-f0-9]{40}$/.test(manifest.commit)) throw new Error('Invalid runtime manifest identity');
  if (!/^3\.12\.[0-9]+$/.test(manifest.python)) throw new Error('Runtime Python must be pinned to an exact 3.12 patch');
  for (const [label, asset] of Object.entries({ source: manifest.source, uv: manifest.uv, ...manifest.tools })) {
    if (!asset || !HEX.test(asset.sha256)) throw new Error(`Invalid ${label} SHA-256 checksum`);
    relative(asset.file, `${label} archive`, true);
    if (asset.url) {
      const url = new URL(asset.url);
      if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Payload URLs require HTTPS without credentials');
    }
    if (label !== 'source') relative(asset.executable, `${label} executable`);
    if (asset.format && !['zip', '7z-sfx'].includes(asset.format)) throw new Error(`Unsupported ${label} archive format`);
  }
  relative(manifest.source.root, 'source root', true);
  for (const tool of Object.keys(manifest.tools || {})) {
    if (!['git', 'rg', 'node'].includes(tool)) throw new Error(`Unsupported runtime tool: ${tool}`);
  }
  return manifest;
}

async function exists(file) {
  try { return (await fs.stat(file)).isFile(); } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

async function checksum(file) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

async function ownedDirectory(dir) {
  await fs.mkdir(dir, { recursive: true });
  if ((await fs.lstat(dir)).isSymbolicLink()) throw new Error('Runtime directory cannot be a symbolic link or junction');
}

async function readJson(file) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

async function writeJson(file, value) {
  const temp = `${file}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temp, `${JSON.stringify(value)}\n`, { flag: 'wx' });
    await fs.rename(temp, file);
  } finally { await fs.rm(temp, { force: true }); }
}

async function withLock(base, fn, signal, progress) {
  const lock = path.join(base, 'bootstrap.lock');
  const token = randomUUID();
  const started = Date.now();
  let announced = false;
  for (;;) {
    signal?.throwIfAborted();
    try {
      // A directory is published atomically. An incomplete owner file is never
      // stolen: crashing in that tiny window requires explicit recovery.
      await fs.mkdir(lock);
      await fs.writeFile(path.join(lock, 'owner.json'), JSON.stringify({ pid: process.pid, token }));
      break;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const owner = await readJson(path.join(lock, 'owner.json'));
      if (owner && Number.isSafeInteger(owner.pid) && owner.pid > 0) {
        let dead = false;
        try { process.kill(owner.pid, 0); } catch (probe) { dead = probe.code === 'ESRCH'; }
        if (dead) {
          // PID identity cannot safely authorize deleting an OS lock: another
          // contender may have replaced it since the read. Never steal a lock.
          throw new Error(`An interrupted runtime setup left a lock. Close Zeus setup, remove only this lock directory, then retry: ${lock}`);
        }
      }
      if (Date.now() - started > MAX_WAIT) throw new Error(`Another Zeus runtime setup is still active. Close it and retry. Lock: ${lock}`);
      if (!announced) { progress('waiting', 'Waiting for another Zeus runtime setup to finish'); announced = true; }
      await delay(250, undefined, { signal });
    }
  }
  try { return await fn(); }
  finally {
    const owner = await readJson(path.join(lock, 'owner.json'));
    if (owner?.token === token) await fs.rm(lock, { recursive: true, force: true });
  }
}

async function assetFile(asset, context) {
  const bundled = path.join(context.manifestDir, asset.file);
  if (await exists(bundled)) {
    if (await checksum(bundled) !== asset.sha256) throw new Error(`Payload checksum mismatch: ${asset.file}`);
    return bundled;
  }
  const cached = path.join(context.downloads, asset.file);
  if (await exists(cached)) {
    if (await checksum(cached) === asset.sha256) return cached;
    await fs.rm(cached);
  }
  if (!asset.url) throw new Error(`Missing payload ${asset.file}; reinstall the complete Zeus package`);
  context.progress('download', `Downloading ${asset.file}`);
  const temp = `${cached}.${randomUUID()}.part`;
  const timeout = AbortSignal.timeout(15 * 60 * 1000);
  const signal = context.signal ? AbortSignal.any([context.signal, timeout]) : timeout;
  try {
    let url = asset.url;
    let response;
    for (let redirects = 0; redirects <= 8; redirects++) {
      const parsed = new URL(url);
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password) throw new Error('Payload redirect requires HTTPS without credentials');
      response = await fetch(url, { signal, redirect: 'manual' });
      if (![301, 302, 303, 307, 308].includes(response.status)) break;
      const next = response.headers.get('location');
      await response.body?.cancel();
      if (!next || redirects === 8) throw new Error('Too many payload redirects');
      url = new URL(next, url).href;
    }
    if (!response.ok || !response.body) throw new Error(`Download failed for ${asset.file}: HTTP ${response.status}`);
    if (Number(response.headers.get('content-length')) > MAX_ARCHIVE) throw new Error('Payload exceeds size limit');
    let size = 0;
    const bound = new Transform({ transform(chunk, encoding, callback) {
      size += chunk.length;
      callback(size > MAX_ARCHIVE ? new Error('Payload exceeds size limit') : null, chunk);
    } });
    await pipeline(Readable.fromWeb(response.body), bound, createWriteStream(temp, { flags: 'wx' }), { signal });
    if (await checksum(temp) !== asset.sha256) throw new Error(`Payload checksum mismatch: ${asset.file}`);
    await fs.rename(temp, cached);
    return cached;
  } finally { await fs.rm(temp, { force: true }); }
}

function terminate(child) {
  if (!child.pid) return;
  const killer = spawn(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'taskkill.exe'),
    ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  killer.on('error', () => child.kill());
}

async function run(command, args, { cwd, env = process.env, signal, timeout = MAX_WAIT } = {}) {
  signal?.throwIfAborted();
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
    let tail = '';
    let stdout = '';
    let cancelled = false;
    const remember = chunk => { tail = (tail + chunk.toString()).slice(-5000); };
    child.stdout.on('data', chunk => { stdout = (stdout + chunk.toString()).slice(-5000); remember(chunk); });
    child.stderr.on('data', remember);
    const abort = () => { cancelled = true; terminate(child); };
    const timer = setTimeout(abort, timeout);
    signal?.addEventListener('abort', abort, { once: true });
    child.on('error', finish);
    child.on('close', code => finish(cancelled ? new Error('Runtime setup was aborted or timed out')
      : code !== 0 ? new Error(`${path.basename(command)} failed (${code}): ${tail.replace(/https?:\/\/[^\s/@]+:[^\s/@]+@/g, 'https://[redacted]@')}`) : null));
    function finish(error) {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      if (error) reject(error); else resolve(stdout.trim());
    }
  });
}

// Keep the reviewed project's uv settings while excluding ambient user/global
// uv.toml. Python validates the section extraction against the complete TOML
// parser, so future multiline or table syntax cannot silently change settings.
const PROJECT_UV_CONFIG = String.raw`
import pathlib, re, sys, tomllib
source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
expected = tomllib.loads(source).get("tool", {}).get("uv", {})
lines = []
selected = False
for line in source.splitlines(keepends=True):
    header = re.match(r"^\s*(\[\[?)([^\]\r\n]+)(\]\]?)\s*(?:#.*)?$", line.rstrip("\r\n"))
    if header:
        table = header.group(2).strip()
        selected = table == "tool.uv" or table.startswith("tool.uv.")
        if selected and table != "tool.uv":
            lines.append(header.group(1) + table[len("tool.uv."):] + header.group(3) + "\n")
        continue
    if selected:
        lines.append(line)
output = "".join(lines)
if tomllib.loads(output) != expected:
    raise RuntimeError("Cannot preserve reviewed project uv configuration")
pathlib.Path(sys.argv[2]).write_text(output, encoding="utf-8")
`;

/** uv #19622 can fail only the optional Windows minor-version junction after
 * installing a working interpreter. Recover that exact error, never an install
 * or download failure, and bind subsequent commands to the verified patch path. */
export async function recoverManagedPython(error, { pythonRoot, version, env, signal }) {
  const expected = path.resolve(pythonRoot, `cpython-${version}-windows-x86_64-none`);
  const marker = `Missing expected target directory for Python minor version link at ${expected}`;
  if (!(error instanceof Error) || !error.message.split(/\r?\n/).some(line => line.endsWith(marker))) throw error;
  const executable = path.join(expected, 'python.exe');
  let actual;
  try {
    const physicalRoot = await fs.realpath(pythonRoot);
    const physicalExecutable = path.join(physicalRoot, path.basename(expected), 'python.exe');
    actual = await fs.realpath(executable);
    if (actual.toLowerCase() !== physicalExecutable.toLowerCase()) throw new Error('Python resolves outside its pinned patch directory');
    const identity = JSON.parse(await run(actual, ['-I', '-c',
      'import json,ssl,sqlite3,sys,struct; print(json.dumps({"version":".".join(map(str,sys.version_info[:3])),"implementation":sys.implementation.name,"bits":struct.calcsize("P")*8}))'],
    { cwd: expected, env, signal, timeout: 30000 }));
    if (identity.version !== version || identity.implementation !== 'cpython' || identity.bits !== 64) throw new Error('Installed Python does not match the pinned runtime');
  } catch (validation) {
    throw new Error(`Windows Python alias recovery refused: ${validation.message}`, { cause: error });
  }
  return actual;
}

// .NET's archive reader is present on supported Windows. Explicit entry checks
// reject traversal, NTFS streams and Unix symlinks before any entry is written.
const EXTRACT = `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($env:ZEUS_ARCHIVE_PATH)
try {
  $root = [IO.Path]::GetFullPath($env:ZEUS_EXTRACT_ROOT).TrimEnd('\\') + '\\'
  $total = [long]0
  if ($archive.Entries.Count -gt 100000) { throw 'Too many archive entries' }
  foreach ($entry in $archive.Entries) {
    $name = $entry.FullName.Replace('\\', '/')
    if ($name.StartsWith('/') -or $name.Contains(':') -or $name.Split('/') -contains '..' -or (($entry.ExternalAttributes -shr 16) -band 61440) -eq 40960) { throw 'Unsafe archive entry' }
    $destination = [IO.Path]::GetFullPath([IO.Path]::Combine($root, $name))
    if (-not $destination.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive path escaped extraction root' }
    $total += $entry.Length
    if ($total -gt 3221225472 -or $entry.Length -gt 805306368) { throw 'Extracted archive exceeds size limit' }
  }
  foreach ($entry in $archive.Entries) {
    $destination = [IO.Path]::GetFullPath([IO.Path]::Combine($root, $entry.FullName))
    if ($entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('\\')) { [IO.Directory]::CreateDirectory($destination) | Out-Null; continue }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $false)
  }
} finally { $archive.Dispose() }
`;

async function extract(archive, destination, format, context) {
  await ownedDirectory(destination);
  if (format === '7z-sfx') {
    await run(archive, ['-y', `-o${destination}`], { cwd: destination, signal: context.signal, timeout: 180000 });
  } else {
    const powershell = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    await run(powershell, ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(EXTRACT, 'utf16le').toString('base64')],
      { cwd: destination, signal: context.signal, timeout: 180000, env: { ...process.env, ZEUS_ARCHIVE_PATH: archive, ZEUS_EXTRACT_ROOT: destination } });
  }
}

async function installAsset(name, asset, destination, context) {
  const receipt = path.join(destination, '.zeus-asset.json');
  const previous = await readJson(receipt);
  if (previous?.sha256 === asset.sha256) return;
  if (previous) throw new Error(`Installed ${name} differs from this release; use a new release version`);
  const archive = await assetFile(asset, context);
  const staging = `${destination}.${randomUUID()}.staging`;
  try {
    context.progress('extract', `Preparing ${name}`);
    await extract(archive, staging, asset.format, context);
    const required = name === 'source' ? path.join(asset.root, 'zeus') : asset.executable;
    if (!await exists(path.join(staging, required))) throw new Error(`${name} archive is missing ${required}`);
    await writeJson(path.join(staging, '.zeus-asset.json'), { sha256: asset.sha256 });
    await fs.rename(staging, destination);
  } finally { await fs.rm(staging, { recursive: true, force: true }); }
}

function runtimeEnvironment(runtime, manifest) {
  const env = { ...process.env };
  const directories = [path.dirname(runtime.python)];
  for (const [name, asset] of Object.entries(manifest.tools || {})) {
    const toolRoot = path.join(runtime.base, 'tools', name);
    const executable = path.join(toolRoot, asset.executable);
    directories.push(path.dirname(executable));
    if (name === 'git') {
      directories.push(path.join(toolRoot, 'cmd'), path.join(toolRoot, 'usr', 'bin'));
      env.ZEUS_GIT_BASH_PATH = executable;
    }
    if (name === 'node') env.ZEUS_NODE = executable;
  }
  const pathKey = Object.keys(env).find(key => key.toLowerCase() === 'path') || 'PATH';
  env[pathKey] = [...directories, env[pathKey] || ''].join(path.delimiter);
  env.VIRTUAL_ENV = runtime.venvRoot;
  env.ZEUS_PYTHON = runtime.python;
  env.ZEUS_TUI_DIR = path.join(runtime.root, 'ui-tui');
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ZEUS_DESKTOP_RESOURCES;
  delete env.PYTHONHOME;
  return env;
}

async function definition(manifestPath, runtimeBaseDir) {
  if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('This Zeus runtime package supports Windows x64');
  const manifest = validate(await readJson(path.resolve(manifestPath)));
  const manifestHash = createHash('sha256').update(JSON.stringify(manifest)).digest('hex');
  const storage = runtimeBaseDir || (process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'ZeusAgent', 'runtimes'));
  if (!storage) throw new Error('Windows LOCALAPPDATA is unavailable');
  const base = path.resolve(storage, `${manifest.version}-${manifest.source.sha256.slice(0, 12)}`);
  const root = path.join(base, 'source', manifest.source.root);
  const venvRoot = path.join(root, '.venv');
  const runtime = { base, root, python: path.join(venvRoot, 'Scripts', 'python.exe'), venvRoot, version: manifest.version, commit: manifest.commit };
  return { manifest, manifestHash, runtime };
}

async function cachedRuntime(runtime, manifest, manifestHash) {
  const ready = await readJson(path.join(runtime.base, 'ready.json'));
  if (!ready) return null;
  if (ready.manifestHash !== manifestHash) throw new Error('This release runtime was created from a different manifest; reinstall the matching release');
  const required = [runtime.python, path.join(runtime.root, 'zeus'),
    ...FRONTENDS.map(file => path.join(runtime.root, file)),
    ...Object.entries(manifest.tools || {}).map(([name, asset]) => path.join(runtime.base, 'tools', name, asset.executable))];
  for (const file of required) {
    if (!await exists(file)) throw new Error('Zeus runtime is incomplete; reinstall or remove this version runtime and retry');
  }
  return { ...runtime, env: runtimeEnvironment(runtime, manifest) };
}

/** Read-only resolver for Electron startup; never installs or creates folders. */
export async function readCachedWindowsRuntime({ manifestPath, runtimeBaseDir } = {}) {
  const { manifest, manifestHash, runtime } = await definition(manifestPath, runtimeBaseDir);
  return await cachedRuntime(runtime, manifest, manifestHash);
}

export async function ensureWindowsRuntime({ manifestPath, runtimeBaseDir, onProgress, signal } = {}) {
  signal?.throwIfAborted();
  const { manifest, manifestHash, runtime } = await definition(manifestPath, runtimeBaseDir);
  const { base, root, venvRoot } = runtime;
  const progress = (stage, message) => onProgress?.({ stage, message });
  await ownedDirectory(base);
  const readyFile = path.join(base, 'ready.json');
  return await withLock(base, async () => {
    const cached = await cachedRuntime(runtime, manifest, manifestHash);
    if (cached) return cached;
    const context = { manifestDir: path.dirname(path.resolve(manifestPath)), downloads: path.join(base, 'downloads'), progress, signal };
    await ownedDirectory(context.downloads);
    await installAsset('source', manifest.source, path.join(base, 'source'), context);
    await writeJson(path.join(root, '.zeus-runtime.json'), {
      schemaVersion: 1, manager: 'zeus-windows-release', version: manifest.version, commit: manifest.commit,
    });
    await installAsset('uv', manifest.uv, path.join(base, 'uv'), context);
    for (const [name, asset] of Object.entries(manifest.tools || {})) {
      await ownedDirectory(path.join(base, 'tools'));
      await installAsset(name, asset, path.join(base, 'tools', name), context);
    }
    const uv = path.join(base, 'uv', manifest.uv.executable);
    const inherited = Object.fromEntries(Object.entries(runtimeEnvironment(runtime, manifest)).filter(([key]) => !key.toUpperCase().startsWith('UV_')));
    const env = { ...inherited, UV_PYTHON_INSTALL_DIR: path.join(base, 'python'),
      UV_PROJECT_ENVIRONMENT: venvRoot, UV_CACHE_DIR: path.join(base, 'cache'), UV_LINK_MODE: 'copy', UV_NO_CONFIG: '1' };
    // AppData may be virtualized when launched by an MSIX host. Absolute
    // junction targets must use the physical directory, not that host's alias.
    await ownedDirectory(env.UV_PYTHON_INSTALL_DIR);
    env.UV_PYTHON_INSTALL_DIR = await fs.realpath(env.UV_PYTHON_INSTALL_DIR);
    progress('python', `Installing Python ${manifest.python}`);
    let recoveredPython;
    try {
      await run(uv, ['python', 'install', manifest.python, '--no-bin', '--no-registry', '--no-config'], { cwd: root, env, signal });
    } catch (error) {
      recoveredPython = await recoverManagedPython(error, { pythonRoot: env.UV_PYTHON_INSTALL_DIR, version: manifest.python, env, signal });
      progress('python', 'Python is installed; using its verified executable after a Windows alias error');
    }
    const managedPython = recoveredPython || await run(uv, ['python', 'find', manifest.python, '--managed-python', '--no-config', '--no-project', '--system'], { cwd: root, env, signal });
    const resolvedPython = await fs.realpath(managedPython);
    const managedRoot = `${path.resolve(env.UV_PYTHON_INSTALL_DIR)}${path.sep}`.toLowerCase();
    if (!resolvedPython.toLowerCase().startsWith(managedRoot)) throw new Error('uv selected a Python outside this Zeus runtime');
    const uvConfig = path.join(base, 'uv-project.toml');
    await run(resolvedPython, ['-c', PROJECT_UV_CONFIG, path.join(root, 'pyproject.toml'), uvConfig], { cwd: root, env, signal, timeout: 30000 });
    const { UV_NO_CONFIG, ...syncEnv } = env;
    progress('dependencies', 'Installing locked Zeus dependencies');
    await run(uv, ['sync', '--project', root, '--config-file', uvConfig, '--python', resolvedPython, '--managed-python', '--locked', '--no-default-groups',
      '--extra', 'messaging', '--extra', 'web', '--extra', 'anthropic', '--extra', 'acp', '--extra', 'mcp'], { cwd: root, env: syncEnv, signal });
    progress('verify', 'Checking the installed Zeus runtime');
    for (const file of FRONTENDS) {
      if (!await exists(path.join(root, file))) throw new Error(`Release payload is missing the built frontend: ${file}`);
    }
    await run(runtime.python, ['-c', 'import zeus_cli.main, tui_gateway.server; print("Zeus runtime ready")'], { cwd: root, env, signal, timeout: 120000 });
    if (manifest.tools?.git) await run(env.ZEUS_GIT_BASH_PATH, ['--noprofile', '--norc', '-c', 'printf zeus; git --version; ls / >/dev/null'], { cwd: root, env, signal, timeout: 30000 });
    await writeJson(readyFile, { schemaVersion: 1, manifestHash, version: manifest.version, commit: manifest.commit, createdAt: new Date().toISOString() });
    progress('ready', 'Zeus runtime is ready');
    return { ...runtime, env: runtimeEnvironment(runtime, manifest) };
  }, signal, progress);
}

async function main(argv) {
  if (argv[0] !== '--manifest' || !argv[1] || argv[2] !== '--') throw new Error('Usage: windows-runtime.mjs --manifest <runtime-manifest.json> -- [Zeus arguments]');
  const controller = new AbortController();
  const interrupt = () => controller.abort();
  process.once('SIGINT', interrupt);
  process.once('SIGTERM', interrupt);
  let runtime;
  try { runtime = await ensureWindowsRuntime({ manifestPath: argv[1], signal: controller.signal,
    onProgress: ({ message }) => process.stderr.write(`[Zeus] ${message}\n`) }); }
  finally { process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt); }
  const child = spawn(runtime.python, [path.join(runtime.root, 'zeus'), ...argv.slice(3)], {
    cwd: process.cwd(), env: runtime.env, stdio: 'inherit', shell: false, windowsHide: false,
  });
  // Console children receive Ctrl+C directly on Windows. Python's interactive
  // handler cancels a turn; force-killing its tree here would destroy that UX.
  const interruptChild = () => { if (process.platform !== 'win32') child.kill('SIGINT'); };
  const stop = () => terminate(child);
  process.on('SIGINT', interruptChild);
  process.on('SIGTERM', stop);
  await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', code => { process.exitCode = code ?? 1; resolve(); }); });
  process.removeListener('SIGINT', interruptChild);
  process.removeListener('SIGTERM', stop);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch(error => { process.stderr.write(`Zeus: ${error.message}\n`); process.exitCode = 1; });
}
