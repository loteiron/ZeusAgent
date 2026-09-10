#!/usr/bin/env node
// User-owned, versioned Linux runtime shared by Electron and the npm command.
import * as fs from 'node:fs/promises';
import path from 'node:path';
import { gunzipSync } from 'node:zlib';

import { createHash, randomUUID } from 'node:crypto';
import { constants, createReadStream, createWriteStream } from 'node:fs';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
const MAX_WAIT = 30 * 60 * 1000;
const HEX = /^[a-f0-9]{64}$/;
const FRONTENDS = ['ui-tui/dist/entry.js', 'zeus_cli/web_dist/index.html'];

const MAX_ARCHIVE = 768 * 1024 * 1024;

function relative(value, label, single = false) {
  if (typeof value !== 'string' || !value || value.includes('\\') || value.includes(':')
      || value.startsWith('/') || value.split('/').some(p => !p || p === '.' || p === '..')
      || (single && value.includes('/')) || /[\x00-\x1f]/.test(value)) {
    throw new Error(`Invalid relative ${label} path`);
  }
  return value;
}

/** Only the checksum-pinned uv bootstrap needs extraction before Python exists.
 * Validate its entire small POSIX tar before creating any destination paths. */
export async function extractUvArchive(archive, destination, { signal } = {}) {
  signal?.throwIfAborted();
  if ((await fs.stat(archive)).size > MAX_ARCHIVE) throw new Error('Payload exceeds size limit');
  const bytes = gunzipSync(await fs.readFile(archive), { maxOutputLength: MAX_ARCHIVE });
  const entries = [];
  const seen = new Set();
  let total = 0;
  for (let offset = 0; offset + 512 <= bytes.length;) {
    signal?.throwIfAborted();
    const header = bytes.subarray(offset, offset + 512);
    if (header.every(byte => byte === 0)) break;
    const text = (start, length) => header.subarray(start, start + length).toString('utf8').split('\0')[0];
    const numeric = (start, length) => {
      const value = text(start, length).trim();
      if (!/^[0-7]+$/.test(value)) throw new Error('Unsupported tar numeric field');
      return Number.parseInt(value, 8);
    };
    const expected = numeric(148, 8);
    const actual = header.reduce((sum, byte, index) => sum + (index >= 148 && index < 156 ? 32 : byte), 0);
    if (actual !== expected) throw new Error('Invalid tar header checksum');
    const prefix = text(345, 155);
    const name = relative(`${prefix ? `${prefix}/` : ''}${text(0, 100)}`.replace(/\/$/, ''), 'tar entry');
    if (seen.has(name)) throw new Error('Duplicate tar path');
    seen.add(name);
    const size = numeric(124, 12);
    const kind = header[156];
    if (![0, 48, 53].includes(kind)) throw new Error('Bootstrap uv archive cannot contain links or special files');
    if (size > 256 * 1024 * 1024 || (total += size) > MAX_ARCHIVE || seen.size > 1000) throw new Error('Tar exceeds size limit');
    if (offset + 512 + size > bytes.length) throw new Error('Truncated tar payload');
    entries.push({ name, directory: kind === 53, mode: numeric(100, 8) & 0o777, data: bytes.subarray(offset + 512, offset + 512 + size) });
    offset += 512 + Math.ceil(size / 512) * 512;
  }
  for (const entry of entries) {
    const parts = entry.name.split('/');
    while (parts.pop() && parts.length) {
      if (entries.some(parent => parent.name === parts.join('/') && !parent.directory)) throw new Error('Tar parent is not a directory');
    }
  }
  await fs.mkdir(destination, { mode: 0o700 });
  for (const entry of entries) {
    signal?.throwIfAborted();
    const target = path.join(destination, entry.name);
    await fs.mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
    if (entry.directory) await fs.mkdir(target, { recursive: true, mode: 0o755 });
    else await fs.writeFile(target, entry.data, { flag: 'wx', mode: entry.mode });
  }
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
    if (asset.format && !['tar.gz', 'tar.xz'].includes(asset.format)) throw new Error(`Unsupported ${label} archive format`);
  }
  relative(manifest.source.root, 'source root', true);
  for (const tool of Object.keys(manifest.tools || {})) {
    if (!['node'].includes(tool)) throw new Error(`Unsupported runtime tool: ${tool}`);
  }
  if (manifest.source.format !== 'tar.gz' || manifest.uv.format !== 'tar.gz' || manifest.tools?.node?.format !== 'tar.xz') throw new Error('Linux release requires source/uv tar.gz and Node tar.xz');
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

function terminate(child, signal = 'SIGTERM') {
  if (!child.pid) return;
  try { process.kill(-child.pid, signal); }
  catch (error) { if (error.code !== 'ESRCH') child.kill(signal); }
}

async function run(command, args, { cwd, env = process.env, signal, timeout = MAX_WAIT } = {}) {
  signal?.throwIfAborted();
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, detached: true, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
    let tail = '', stdout = '', cancelled = false, force, settled = false;
    const remember = chunk => { tail = (tail + chunk.toString()).slice(-5000); };
    child.stdout.on('data', chunk => { stdout = (stdout + chunk.toString()).slice(-5000); remember(chunk); });
    child.stderr.on('data', remember);
    const abort = () => {
      if (cancelled) return;
      cancelled = true;
      terminate(child);
      force = setTimeout(() => terminate(child, 'SIGKILL'), 2000);
    };
    const timer = setTimeout(abort, timeout);
    signal?.addEventListener('abort', abort, { once: true });
    child.on('error', finish);
    child.on('close', code => finish(cancelled ? new Error('Runtime setup was aborted or timed out')
      : code !== 0 ? new Error(`${path.basename(command)} failed (${code}): ${tail.replace(/https?:\/\/[^\s/@]+:[^\s/@]+@/g, 'https://[redacted]@')}`) : null));
    function finish(error) {
      if (settled) return;
      settled = true;
      clearTimeout(timer); clearTimeout(force);
      signal?.removeEventListener('abort', abort);
      if (cancelled) terminate(child, 'SIGKILL');
      if (error) reject(error); else resolve(stdout.trim());
    }
  });
}

// Preflight the complete archive before writing. All links are created last;
// no file can be extracted through a link supplied by an earlier tar entry.
const EXTRACT_TAR = String.raw`
import os, pathlib, posixpath, shutil, sys, tarfile
archive, output = map(pathlib.Path, sys.argv[1:3])
members, paths, links, total = [], set(), {}, 0
with tarfile.open(archive, 'r:*') as tf:
    for entry in tf:
        name = entry.name.rstrip('/')
        parts = name.split('/')
        if not name or name.startswith('/') or any(p in ('', '.', '..') for p in parts) or '\\' in name or ':' in name or any(ord(c)<32 for c in name):
            raise ValueError('Unsafe tar entry path')
        if name in paths or len(paths) >= 50000:
            raise ValueError('Duplicate path or too many tar entries')
        paths.add(name)
        total += entry.size
        if entry.size > 256*1024*1024 or total > 768*1024*1024:
            raise ValueError('Tar exceeds size limit')
        if not (entry.isfile() or entry.isdir() or entry.issym()):
            raise ValueError('Unsupported tar special file or hard link')
        if entry.issym():
            target = entry.linkname
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
            if not target or target.startswith('/') or '\\' in target or ':' in target or any(ord(c)<32 for c in target) or resolved == '..' or resolved.startswith('../'):
                raise ValueError('Tar symbolic link escapes its destination')
            links[name] = resolved
        members.append(entry)
    by_name = {entry.name.rstrip('/'): entry for entry in members}
    for name in paths:
        parent = posixpath.dirname(name)
        while parent:
            if parent in by_name and not by_name[parent].isdir():
                raise ValueError('Tar parent is not a directory')
            parent = posixpath.dirname(parent)
    for name, target in links.items():
        visited = {name}
        while target in links:
            if target in visited: raise ValueError('Cyclic tar symbolic link')
            visited.add(target)
            target = links[target]
        if target not in paths:
            raise ValueError('Tar symbolic link target is missing')
    output.mkdir(mode=0o700)
    for entry in members:
        target = output.joinpath(*entry.name.rstrip('/').split('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.isdir(): target.mkdir(exist_ok=True)
        elif entry.isfile():
            with tf.extractfile(entry) as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest, 1024*1024)
            target.chmod(entry.mode & 0o777)
    for entry in members:
        if entry.issym(): output.joinpath(*entry.name.split('/')).symlink_to(entry.linkname)
`;

export async function extractTarArchive(archive, destination, { python, signal, env = process.env } = {}) {
  await run(python, ['-I', '-c', EXTRACT_TAR, archive, destination], { cwd: path.dirname(destination), env, signal, timeout: 120000 });
}

async function installAsset(name, asset, destination, context, python) {
  const previous = await readJson(path.join(destination, '.zeus-asset.json'));
  if (previous?.sha256 === asset.sha256) return;
  if (previous) throw new Error(`Installed ${name} differs from this release; use a new release version`);
  const archive = await assetFile(asset, context);
  const staging = `${destination}.${randomUUID()}.staging`;
  try {
    context.progress('extract', `Preparing ${name}`);
    if (name === 'uv') await extractUvArchive(archive, staging, context);
    else await extractTarArchive(archive, staging, { python, signal: context.signal, env: context.env });
    const required = name === 'source' ? path.join(asset.root, 'zeus') : asset.executable;
    if (!await exists(path.join(staging, required))) throw new Error(`${name} archive is missing ${required}`);
    await writeJson(path.join(staging, '.zeus-asset.json'), { sha256: asset.sha256 });
    await fs.rename(staging, destination);
  } finally { await fs.rm(staging, { recursive: true, force: true }); }
}

function runtimeEnvironment(runtime, manifest) {
  const env = { ...process.env };
  const node = path.join(runtime.base, 'tools', 'node', manifest.tools.node.executable);
  env.PATH = [path.dirname(runtime.python), path.dirname(node), env.PATH || '/usr/local/bin:/usr/bin:/bin'].join(path.delimiter);
  env.VIRTUAL_ENV = runtime.venvRoot;
  env.ZEUS_PYTHON = runtime.python;
  env.ZEUS_NODE = node;
  env.ZEUS_TUI_DIR = path.join(runtime.root, 'ui-tui');
  delete env.ELECTRON_RUN_AS_NODE; delete env.ZEUS_DESKTOP_RESOURCES; delete env.PYTHONHOME; delete env.PYTHONPATH;
  return env;
}

async function definition(manifestPath, runtimeBaseDir) {
  if (process.platform !== 'linux' || process.arch !== 'x64') throw new Error('This Zeus runtime package supports Linux x64');
  const manifest = validate(await readJson(path.resolve(manifestPath)));
  const manifestHash = createHash('sha256').update(JSON.stringify(manifest)).digest('hex');
  const dataHome = process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local', 'share');
  if (!path.isAbsolute(dataHome)) throw new Error('XDG_DATA_HOME must be an absolute path');
  const storage = runtimeBaseDir || path.join(dataHome, 'ZeusAgent', 'runtimes');
  const base = path.resolve(storage, `${manifest.version}-${manifest.source.sha256.slice(0, 12)}`);
  const root = path.join(base, 'source', manifest.source.root);
  const venvRoot = path.join(root, '.venv');
  return { manifest, manifestHash, runtime: { base, root, venvRoot, python: path.join(venvRoot, 'bin', 'python'), version: manifest.version, commit: manifest.commit } };
}

async function cachedRuntime(runtime, manifest, manifestHash) {
  const ready = await readJson(path.join(runtime.base, 'ready.json'));
  if (!ready) return null;
  if (ready.manifestHash !== manifestHash) throw new Error('This release runtime was created from a different manifest; reinstall the matching release');
  for (const file of [runtime.python, path.join(runtime.root, 'zeus'), ...FRONTENDS.map(file => path.join(runtime.root, file)), path.join(runtime.base, 'tools', 'node', manifest.tools.node.executable)]) {
    if (!await exists(file)) throw new Error('Zeus runtime is incomplete; reinstall or remove this version runtime and retry');
  }
  for (const file of [runtime.python, path.join(runtime.base, 'tools', 'node', manifest.tools.node.executable)]) {
    try { await fs.access(file, constants.X_OK); }
    catch { throw new Error('Zeus runtime executable permissions are missing; reinstall this release runtime'); }
  }
  return { ...runtime, env: runtimeEnvironment(runtime, manifest) };
}

export async function readCachedLinuxRuntime({ manifestPath, runtimeBaseDir } = {}) {
  const { manifest, manifestHash, runtime } = await definition(manifestPath, runtimeBaseDir);
  return await cachedRuntime(runtime, manifest, manifestHash);
}

export async function ensureLinuxRuntime({ manifestPath, runtimeBaseDir, onProgress, signal } = {}) {
  signal?.throwIfAborted();
  const { manifest, manifestHash, runtime } = await definition(manifestPath, runtimeBaseDir);
  if (process.getuid?.() === 0) throw new Error('Run Zeus as your normal user; do not run its runtime setup with sudo');
  for (const command of ['git', 'rg']) {
    try { await run(command, ['--version'], { signal, timeout: 10000 }); }
    catch (error) { throw new Error(`Zeus requires system ${command}. Install git and ripgrep with your package manager, then retry. ${error.message}`); }
  }
  const { base, root, venvRoot } = runtime;
  const progress = (stage, message) => onProgress?.({ stage, message });
  await ownedDirectory(base);
  return await withLock(base, async () => {
    const cached = await cachedRuntime(runtime, manifest, manifestHash);
    if (cached) return cached;
    const context = { manifestDir: path.dirname(path.resolve(manifestPath)), downloads: path.join(base, 'downloads'), progress, signal };
    await ownedDirectory(context.downloads);
    await installAsset('uv', manifest.uv, path.join(base, 'uv'), context);
    const uv = path.join(base, 'uv', manifest.uv.executable);
    const inherited = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('UV_') && !['PYTHONHOME', 'PYTHONPATH', 'ELECTRON_RUN_AS_NODE', 'ZEUS_DESKTOP_RESOURCES'].includes(key)));
    const env = { ...inherited, UV_PYTHON_INSTALL_DIR: path.join(base, 'python'), UV_PROJECT_ENVIRONMENT: venvRoot, UV_CACHE_DIR: path.join(base, 'cache'), UV_LINK_MODE: 'copy', UV_NO_CONFIG: '1' };
    await ownedDirectory(env.UV_PYTHON_INSTALL_DIR);
    env.UV_PYTHON_INSTALL_DIR = await fs.realpath(env.UV_PYTHON_INSTALL_DIR);
    progress('python', `Installing Python ${manifest.python}`);
    await run(uv, ['python', 'install', manifest.python, '--no-bin', '--no-config'], { cwd: base, env, signal });
    const managedPython = await run(uv, ['python', 'find', manifest.python, '--managed-python', '--no-config', '--no-project', '--system'], { cwd: base, env, signal });
    const resolvedPython = await fs.realpath(managedPython);
    if (!resolvedPython.startsWith(`${env.UV_PYTHON_INSTALL_DIR}${path.sep}`)) throw new Error('uv selected a Python outside this Zeus runtime');
    const identity = await run(resolvedPython, ['-I', '-c', 'import sys,ssl,sqlite3; print(".".join(map(str,sys.version_info[:3])))'], { cwd: base, env, signal, timeout: 30000 });
    if (identity !== manifest.python) throw new Error('Managed Python does not match the pinned patch version');
    context.env = env;
    await installAsset('source', manifest.source, path.join(base, 'source'), context, resolvedPython);
    await ownedDirectory(path.join(base, 'tools'));
    await installAsset('node', manifest.tools.node, path.join(base, 'tools', 'node'), context, resolvedPython);
    const executionEnv = runtimeEnvironment(runtime, manifest);
    env.PATH = executionEnv.PATH;
    env.ZEUS_NODE = executionEnv.ZEUS_NODE;
    env.ZEUS_TUI_DIR = executionEnv.ZEUS_TUI_DIR;
    await writeJson(path.join(root, '.zeus-runtime.json'), { schemaVersion: 1, manager: 'zeus-linux-release', version: manifest.version, commit: manifest.commit });
    const uvConfig = path.join(base, 'uv-project.toml');
    await run(resolvedPython, ['-I', '-c', PROJECT_UV_CONFIG, path.join(root, 'pyproject.toml'), uvConfig], { cwd: root, env, signal, timeout: 30000 });
    const { UV_NO_CONFIG, ...syncEnv } = env;
    progress('dependencies', 'Installing locked Zeus dependencies');
    await run(uv, ['sync', '--project', root, '--config-file', uvConfig, '--python', resolvedPython, '--managed-python', '--locked', '--no-default-groups', '--extra', 'messaging', '--extra', 'web', '--extra', 'anthropic', '--extra', 'acp', '--extra', 'mcp'], { cwd: root, env: syncEnv, signal });
    progress('verify', 'Checking the installed Zeus runtime');
    for (const file of FRONTENDS) if (!await exists(path.join(root, file))) throw new Error(`Release payload is missing the built frontend: ${file}`);
    await run(runtime.python, ['-I', '-c', `import sys; sys.path.insert(0, ${JSON.stringify(root)}); import zeus_cli.main, tui_gateway.server; print("Zeus runtime ready")`], { cwd: root, env: runtimeEnvironment(runtime, manifest), signal, timeout: 120000 });
    await run(path.join(base, 'tools', 'node', manifest.tools.node.executable), ['--version'], { cwd: root, env, signal, timeout: 10000 });
    await writeJson(path.join(base, 'ready.json'), { schemaVersion: 1, manifestHash, version: manifest.version, commit: manifest.commit, createdAt: new Date().toISOString() });
    progress('ready', 'Zeus runtime is ready');
    return { ...runtime, env: runtimeEnvironment(runtime, manifest) };
  }, signal, progress);
}

async function main(argv) {
  if (argv[0] !== '--manifest' || !argv[1] || argv[2] !== '--') throw new Error('Usage: linux-runtime.mjs --manifest <runtime-manifest.json> -- [Zeus arguments]');
  const controller = new AbortController();
  const interrupt = () => controller.abort();
  process.on('SIGINT', interrupt); process.on('SIGTERM', interrupt);
  let runtime;
  try { runtime = await ensureLinuxRuntime({ manifestPath: argv[1], signal: controller.signal, onProgress: ({ message }) => process.stderr.write(`[Zeus] ${message}\n`) }); }
  finally { process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt); }
  const child = spawn(runtime.python, [path.join(runtime.root, 'zeus'), ...argv.slice(3)], { cwd: process.cwd(), env: runtime.env, stdio: 'inherit', shell: false });
  // Child shares the foreground console and receives terminal Ctrl+C itself.
  const keepConsoleOwner = () => { if (!process.stdin.isTTY) child.kill('SIGINT'); };
  const stop = () => child.kill('SIGTERM');
  process.on('SIGINT', keepConsoleOwner); process.on('SIGTERM', stop);
  try { await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', (code, signal) => { process.exitCode = code ?? (signal === 'SIGINT' ? 130 : 1); resolve(); }); }); }
  finally { process.removeListener('SIGINT', keepConsoleOwner); process.removeListener('SIGTERM', stop); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch(error => { process.stderr.write(`Zeus: ${error.message}\n`); process.exitCode = 1; });
}
