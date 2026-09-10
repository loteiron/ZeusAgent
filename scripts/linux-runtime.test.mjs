import test from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { gzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { execFileSync, spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { extractUvArchive, extractTarArchive, readCachedLinuxRuntime, ensureLinuxRuntime } from './linux-runtime.mjs';

function tar(entries) {
  const chunks = [];
  for (const [name, text, kind = 48, link = ''] of entries) {
    const data = Buffer.from(text);
    const header = Buffer.alloc(512);
    header.write(name, 0, 100); header.write('0000755\0', 100);
    header.write(`${data.length.toString(8).padStart(11, '0')}\0`, 124);
    header.fill(32, 148, 156); header[156] = kind; header.write(link, 157, 100);
    header.write('ustar\0', 257);
    const sum = header.reduce((total, byte) => total + byte, 0);
    header.write(`${sum.toString(8).padStart(6, '0')}\0 `, 148);
    chunks.push(header, data, Buffer.alloc((512 - data.length % 512) % 512));
  }
  return gzipSync(Buffer.concat([...chunks, Buffer.alloc(1024)]));
}

test('uv extraction rejects traversal before publishing any executable', async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-runtime-'));
  try {
    const archive = path.join(base, 'uv.tar.gz');
    const destination = path.join(base, 'extracted');
    await fs.writeFile(archive, tar([['uv/uv', 'good'], ['../escaped', 'bad']]));
    await assert.rejects(extractUvArchive(archive, destination), /path|traversal/i);
    await assert.rejects(fs.stat(destination), { code: 'ENOENT' });
    await assert.rejects(fs.stat(path.join(base, 'escaped')), { code: 'ENOENT' });
  } finally { await fs.rm(base, { recursive: true, force: true }); }
});

test('uv extraction publishes only reviewed file bytes and refuses collisions and links', async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-tar-'));
  try {
    const archive = path.join(base, 'uv.tar.gz');
    await fs.writeFile(archive, tar([['uv/uv', '#!/bin/sh\nprintf uv']]));
    await extractUvArchive(archive, path.join(base, 'good'));
    assert.equal(await fs.readFile(path.join(base, 'good/uv/uv'), 'utf8'), '#!/bin/sh\nprintf uv');
    for (const [name, entries] of [
      ['duplicate', [['uv/uv', 'one'], ['uv/uv', 'two']]],
      ['parent', [['uv', 'one'], ['uv/uv', 'two']]],
      ['link', [['uv/uv', '', 50, '/bin/sh']]],
    ]) {
      await fs.writeFile(archive, tar(entries));
      await assert.rejects(extractUvArchive(archive, path.join(base, name)), /Duplicate|parent|links/);
      await assert.rejects(fs.stat(path.join(base, name)), { code: 'ENOENT' });
    }
  } finally { await fs.rm(base, { recursive: true, force: true }); }
});

const python = process.env.ZEUS_PYTHON || (process.platform === 'win32' ? undefined : 'python3');
test('managed-Python tar preflight rejects outside and duplicate paths before file creation', { skip: !python }, async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-python-tar-'));
  try {
    const archive = path.join(base, 'source.tar.gz');
    for (const [name, entries] of [
      ['traversal', [['safe/code.py', 'good'], ['../outside', 'bad']]],
      ['duplicate', [['source/a', 'first'], ['source/a', 'second']]],
      ['outside-link', [['source/a', '', 50, '../../outside']]],
      ['parent-link', [['source/a', 'value'], ['source/b', '', 50, 'a'], ['source/b/child', 'value']]],
    ]) {
      await fs.writeFile(archive, tar(entries));
      await assert.rejects(extractTarArchive(archive, path.join(base, name), { python }), /Unsafe|Duplicate|escapes|parent/);
      await assert.rejects(fs.stat(path.join(base, name)), { code: 'ENOENT' });
    }
  } finally { await fs.rm(base, { recursive: true, force: true }); }
});

test('Node tar preserves only contained npm links and executable mode', { skip: !python || process.platform !== 'linux' }, async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-npm-links-'));
  try {
    const archive = path.join(base, 'node.tar.gz');
    await fs.writeFile(archive, tar([['node/lib/npm.mjs', 'console.log(1)'], ['node/bin/npm', '', 50, '../lib/npm.mjs']]));
    await extractTarArchive(archive, path.join(base, 'node'), { python });
    assert.equal(await fs.readlink(path.join(base, 'node/node/bin/npm')), '../lib/npm.mjs');
    assert.equal(await fs.readFile(path.join(base, 'node/node/bin/npm'), 'utf8'), 'console.log(1)');
    assert.equal((await fs.stat(path.join(base, 'node/node/lib/npm.mjs'))).mode & 0o777, 0o755);
  } finally { await fs.rm(base, { recursive: true, force: true }); }
});

function manifest() {
  return { schemaVersion: 1, version: '0.22.0', commit: 'a'.repeat(40), python: '3.12.12',
    source: { file: 'source.tar.gz', format: 'tar.gz', root: 'zeus-agent', sha256: '1'.repeat(64) },
    uv: { file: 'uv.tar.gz', format: 'tar.gz', executable: 'uv/uv', sha256: '2'.repeat(64) },
    tools: { node: { file: 'node.tar.xz', format: 'tar.xz', executable: 'node/bin/node', sha256: '3'.repeat(64) } } };
}

test('cached resolver is read-only and binds readiness to the complete release manifest', { skip: process.platform !== 'linux' }, async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-cache-'));
  try {
    const spec = manifest(), manifestPath = path.join(base, 'runtime-manifest.json'), runtimeBaseDir = path.join(base, 'runtimes');
    await fs.writeFile(manifestPath, JSON.stringify(spec));
    assert.equal(await readCachedLinuxRuntime({ manifestPath, runtimeBaseDir }), null);
    await assert.rejects(fs.stat(runtimeBaseDir), { code: 'ENOENT' });
    const runtime = path.join(runtimeBaseDir, `${spec.version}-${spec.source.sha256.slice(0, 12)}`);
    for (const file of ['source/zeus-agent/.venv/bin/python', 'source/zeus-agent/zeus', 'source/zeus-agent/ui-tui/dist/entry.js', 'source/zeus-agent/zeus_cli/web_dist/index.html', 'tools/node/node/bin/node']) {
      const target = path.join(runtime, file); await fs.mkdir(path.dirname(target), { recursive: true }); await fs.writeFile(target, 'fixture', { mode: 0o755 });
    }
    await fs.writeFile(path.join(runtime, 'ready.json'), JSON.stringify({ manifestHash: createHash('sha256').update(JSON.stringify(spec)).digest('hex') }));
    const found = await readCachedLinuxRuntime({ manifestPath, runtimeBaseDir });
    assert.equal(found.root, path.join(runtime, 'source/zeus-agent'));
    assert.equal(found.venvRoot, path.dirname(path.dirname(found.python)));
    assert.equal(found.env.ZEUS_TUI_DIR, path.join(found.root, 'ui-tui'));
    assert.equal(found.env.ZEUS_HOME, process.env.ZEUS_HOME);
    assert.equal(found.env.ELECTRON_RUN_AS_NODE, undefined);
    await fs.chmod(found.python, 0o644);
    await assert.rejects(readCachedLinuxRuntime({ manifestPath, runtimeBaseDir }), /executable permissions/);
    await fs.chmod(found.python, 0o755);
    spec.tools.node.sha256 = '4'.repeat(64);
    await fs.writeFile(manifestPath, JSON.stringify(spec));
    await assert.rejects(readCachedLinuxRuntime({ manifestPath, runtimeBaseDir }), /different manifest/);
  } finally { await fs.rm(base, { recursive: true, force: true }); }
});

test('a non-TTY SIGINT reaches the real Python child after cached runtime startup', { skip: process.platform !== 'linux' || process.getuid?.() === 0 }, async t => {
  try { execFileSync('rg', ['--version']); } catch { return t.skip('ripgrep is a documented host prerequisite'); }
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-cli-signal-'));
  let child, pythonPid;
  try {
    const spec = manifest(), manifestPath = path.join(base, 'runtime-manifest.json');
    const runtime = path.join(base, 'data/ZeusAgent/runtimes', `${spec.version}-${spec.source.sha256.slice(0, 12)}`);
    const root = path.join(runtime, 'source/zeus-agent');
    const witness = path.join(base, 'python-ready');
    await fs.writeFile(manifestPath, JSON.stringify(spec));
    for (const file of ['.venv/bin', 'ui-tui/dist', 'zeus_cli/web_dist']) await fs.mkdir(path.join(root, file), { recursive: true });
    const interpreter = execFileSync(python || 'python3', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).trim();
    await fs.symlink(interpreter, path.join(root, '.venv/bin/python'));
    await fs.writeFile(path.join(root, 'ui-tui/dist/entry.js'), 'fixture');
    await fs.writeFile(path.join(root, 'zeus_cli/web_dist/index.html'), 'fixture');
    await fs.writeFile(path.join(root, 'zeus'), 'import os,pathlib,signal,sys,time\nsignal.signal(signal.SIGINT, lambda *_: sys.exit(23))\npathlib.Path(os.environ["ZEUS_TEST_WITNESS"]).write_text(str(os.getpid()))\nwhile True: time.sleep(0.1)\n');
    const node = path.join(runtime, 'tools/node/node/bin/node');
    await fs.mkdir(path.dirname(node), { recursive: true }); await fs.writeFile(node, 'fixture', { mode: 0o755 });
    await fs.writeFile(path.join(runtime, 'ready.json'), JSON.stringify({ manifestHash: createHash('sha256').update(JSON.stringify(spec)).digest('hex') }));
    child = spawn(process.execPath, [fileURLToPath(new URL('./linux-runtime.mjs', import.meta.url)), '--manifest', manifestPath, '--'], {
      cwd: base, stdio: 'ignore', env: { ...process.env, XDG_DATA_HOME: path.join(base, 'data'), ZEUS_TEST_WITNESS: witness },
    });
    const exited = new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', resolve); });
    for (let attempt = 0; attempt < 100; attempt++) {
      try { pythonPid = Number(await fs.readFile(witness, 'utf8')); if (pythonPid) break; } catch {}
      await delay(50);
    }
    assert.ok(pythonPid, 'cached CLI did not start its Python child');
    child.kill('SIGINT');
    assert.equal(await Promise.race([exited, delay(3000).then(() => 'timed out')]), 23);
  } finally {
    child?.kill('SIGTERM');
    if (pythonPid) { try { process.kill(pythonPid, 'SIGKILL'); } catch {} }
    await fs.rm(base, { recursive: true, force: true });
  }
});

test('missing host tools stop setup before creating user runtime directories', { skip: process.platform !== 'linux' || process.getuid?.() === 0 }, async () => {
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-prereq-'));
  const originalPath = process.env.PATH;
  try {
    const manifestPath = path.join(base, 'runtime-manifest.json'), runtimeBaseDir = path.join(base, 'runtimes');
    await fs.writeFile(manifestPath, JSON.stringify(manifest()));
    process.env.PATH = '';
    await assert.rejects(ensureLinuxRuntime({ manifestPath, runtimeBaseDir }), /requires system git/);
    await assert.rejects(fs.stat(runtimeBaseDir), { code: 'ENOENT' });
  } finally { process.env.PATH = originalPath; await fs.rm(base, { recursive: true, force: true }); }
});

test('a corrupt bundled uv asset never executes and releases the setup lock', { skip: process.platform !== 'linux' || process.getuid?.() === 0 }, async t => {
  try { execFileSync('rg', ['--version']); } catch { return t.skip('ripgrep is a documented host prerequisite'); }
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-corrupt-'));
  try {
    const manifestPath = path.join(base, 'runtime-manifest.json'), runtimeBaseDir = path.join(base, 'runtimes'), spec = manifest();
    const witness = path.join(base, 'should-not-run');
    await fs.writeFile(manifestPath, JSON.stringify(spec));
    await fs.writeFile(path.join(base, 'uv.tar.gz'), tar([['uv/uv', `#!/bin/sh\ntouch '${witness}'`]]));
    await assert.rejects(ensureLinuxRuntime({ manifestPath, runtimeBaseDir }), /checksum mismatch/);
    await assert.rejects(fs.stat(witness), { code: 'ENOENT' });
    const runtime = path.join(runtimeBaseDir, `${spec.version}-${spec.source.sha256.slice(0, 12)}`);
    await assert.rejects(fs.stat(path.join(runtime, 'bootstrap.lock')), { code: 'ENOENT' });
    await assert.rejects(fs.stat(path.join(runtime, 'ready.json')), { code: 'ENOENT' });
  } finally { await fs.rm(base, { recursive: true, force: true }); }
});

test('cancelled setup kills its real process group and a waiting caller cannot steal its lock', { skip: process.platform !== 'linux' || process.getuid?.() === 0 }, async t => {
  try { execFileSync('rg', ['--version']); } catch { return t.skip('ripgrep is a documented host prerequisite'); }
  const base = await fs.mkdtemp(path.join(os.tmpdir(), 'zeus-linux-cancel-'));
  const beforeWitness = process.env.ZEUS_TEST_WITNESS;
  const owner = new AbortController(), waiter = new AbortController();
  let pending, pids = [];
  try {
    const spec = manifest(), manifestPath = path.join(base, 'runtime-manifest.json'), runtimeBaseDir = path.join(base, 'runtimes');
    const witness = path.join(base, 'pids');
    // The checksum-bound fixture exercises the real spawn/abort path while
    // deliberately stopping before any Python provisioning or dependency work.
    const fixture = tar([['uv/uv', '#!/bin/sh\nsleep 60 &\nprintf "%s %s" "$$" "$!" > "$ZEUS_TEST_WITNESS"\nwait\n']]);
    spec.uv.sha256 = createHash('sha256').update(fixture).digest('hex');
    await fs.writeFile(path.join(base, 'uv.tar.gz'), fixture);
    await fs.writeFile(manifestPath, JSON.stringify(spec));
    process.env.ZEUS_TEST_WITNESS = witness;
    pending = ensureLinuxRuntime({ manifestPath, runtimeBaseDir, signal: owner.signal });
    const outcome = assert.rejects(pending, /aborted|timed out/);
    for (let attempt = 0; attempt < 100; attempt++) {
      try { pids = (await fs.readFile(witness, 'utf8')).trim().split(' ').map(Number); if (pids.length === 2) break; } catch {}
      await delay(50);
    }
    assert.equal(pids.length, 2, 'fixture child never started');
    const runtime = path.join(runtimeBaseDir, `${spec.version}-${spec.source.sha256.slice(0, 12)}`);
    const ownerBefore = await fs.readFile(path.join(runtime, 'bootstrap.lock/owner.json'), 'utf8');
    const waiting = ensureLinuxRuntime({ manifestPath, runtimeBaseDir, signal: waiter.signal });
    const waitingOutcome = assert.rejects(waiting, /abort/i);
    await delay(100); waiter.abort(); await waitingOutcome;
    assert.equal(await fs.readFile(path.join(runtime, 'bootstrap.lock/owner.json'), 'utf8'), ownerBefore);
    owner.abort(); await outcome;
    for (const pid of pids) {
      let state = '';
      try { state = execFileSync('ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf8' }).trim(); } catch {}
      assert.ok(!state || state.startsWith('Z'), `cancelled bootstrap left pid ${pid} running (${state})`);
    }
    await assert.rejects(fs.stat(path.join(runtime, 'bootstrap.lock')), { code: 'ENOENT' });
    await assert.rejects(fs.stat(path.join(runtime, 'ready.json')), { code: 'ENOENT' });
  } finally {
    owner.abort(); waiter.abort(); await pending?.catch(() => {});
    for (const pid of pids) { try { process.kill(pid, 'SIGKILL'); } catch {} }
    if (beforeWitness === undefined) delete process.env.ZEUS_TEST_WITNESS; else process.env.ZEUS_TEST_WITNESS = beforeWitness;
    await fs.rm(base, { recursive: true, force: true });
  }
});
