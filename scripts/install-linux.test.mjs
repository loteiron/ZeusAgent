import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, writeFile, copyFile, chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

const stager = await import('./stage_zeus_npm.mjs');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
function run(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', timeout: 60_000, ...options });
  assert.ifError(result.error);
  return result;
}
function succeeded(result) { assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`); return result; }

test('release installer embeds exact package and Node digests without unresolved template values', async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus installer pins '));
  const archive = path.join(scratch, 'loteiron-zeus-agent-1.2.3.tgz');
  await writeFile(archive, 'fixture package bytes');
  const manifest = path.join(scratch, 'linux.json');
  await writeFile(manifest, JSON.stringify({ version: '1.2.3', tools: { node: {
    file: 'node-v22.23.2-linux-x64.tar.xz', format: 'tar.xz', sha256: 'a'.repeat(64),
    url: 'https://nodejs.org/dist/v22.23.2/node-v22.23.2-linux-x64.tar.xz', executable: 'node-v22.23.2-linux-x64/bin/node',
  } } }));
  const output = path.join(scratch, 'install-linux.sh');
  await stager.stageLinuxInstaller({ packagePath: archive, linuxManifestPath: manifest, outputPath: output });
  const script = await readFile(output, 'utf8');
  assert.ok(script.includes(digest(await readFile(archive))));
  assert.ok(script.includes('a'.repeat(64)));
  assert.ok(script.includes('https://github.com/loteiron/ZeusAgent/releases/download/v1.2.3/loteiron-zeus-agent-1.2.3.tgz'));
  assert.ok(!script.includes('@@ZEUS_'));
  await assert.rejects(stager.stageLinuxInstaller({ packagePath: archive, linuxManifestPath: manifest, outputPath: output }), /exist/i);
  assert.equal(await readFile(output, 'utf8'), script);
});

test('standalone Linux install uses private Node from any directory, preserves profiles and refuses foreign commands', {
  skip: process.platform !== 'linux', timeout: 180_000,
}, async () => {
  const scratch = await mkdtemp(path.join(tmpdir(), 'zeus Linux install Türkçe '));
  const assets = path.join(scratch, 'assets');
  const payload = path.join(scratch, 'payload');
  await mkdir(assets);
  await mkdir(path.join(payload, 'package/bin'), { recursive: true });
  await mkdir(path.join(payload, 'node-fixture/bin'), { recursive: true });
  await copyFile(process.execPath, path.join(payload, 'node-fixture/bin/node'));
  await chmod(path.join(payload, 'node-fixture/bin/node'), 0o755);
  await writeFile(path.join(payload, 'package/bin/zeus.mjs'), [
    "import {appendFileSync} from 'node:fs';",
    "appendFileSync(process.env.ZEUS_INSTALL_TEST_OBSERVER, JSON.stringify({cwd:process.cwd(), argv:process.argv.slice(2), exe:process.execPath})+'\\n');",
    "process.exitCode=process.argv.includes('--version') ? 0 : 23;",
  ].join('\n'));
  const packagePath = path.join(assets, 'loteiron-zeus-agent-1.2.3.tgz');
  const nodePath = path.join(assets, 'node-fixture.tar.xz');
  succeeded(run('tar', ['-cJf', nodePath, '-C', payload, 'node-fixture']));
  const manifest = path.join(scratch, 'linux.json');
  await writeFile(manifest, JSON.stringify({ version: '1.2.3', tools: { node: {
    file: path.basename(nodePath), url: 'https://example.invalid/node-fixture.tar.xz', sha256: digest(await readFile(nodePath)),
    executable: 'node-fixture/bin/node', format: 'tar.xz',
  } } }));
  await copyFile(manifest, path.join(payload, 'package/linux-runtime-manifest.json'));
  succeeded(run('tar', ['-czf', packagePath, '-C', payload, 'package']));
  const installer = path.join(scratch, 'install-linux.sh');
  await stager.stageLinuxInstaller({ packagePath, linuxManifestPath: manifest, outputPath: installer });
  const userHome = path.join(scratch, 'home Türkçe');
  const caller = path.join(scratch, 'project with spaces');
  await mkdir(userHome);
  await mkdir(caller);
  await writeFile(path.join(userHome, '.bashrc'), '# User configuration must survive\n');
  const observer = path.join(scratch, 'observed.jsonl');
  const env = { ...process.env, HOME: userHome, XDG_DATA_HOME: path.join(userHome, '.local/share'), ZEUS_INSTALL_TEST_OBSERVER: observer };
  succeeded(run('bash', [installer, '--assets', assets], { cwd: caller, env }));
  const profile = await readFile(path.join(userHome, '.bashrc'), 'utf8');
  assert.ok(profile.startsWith('# User configuration must survive\n'));
  succeeded(run('bash', [installer, '--assets', assets], { cwd: caller, env }));
  assert.equal(await readFile(path.join(userHome, '.bashrc'), 'utf8'), profile, 'repeat install must not duplicate or replace user PATH blocks');
  const invoked = run('bash', ['-c', 'source "$HOME/.bashrc"; zeus --query \'Türkçe & $ literal\''], { cwd: caller, env });
  assert.equal(invoked.status, 23, invoked.stderr);
  const observed = (await readFile(observer, 'utf8')).trim().split('\n').map(JSON.parse);
  assert.deepEqual(observed.at(-1).argv, ['--query', 'Türkçe & $ literal']);
  assert.equal(observed.at(-1).cwd, caller);
  assert.ok(observed.every(item => item.exe.startsWith(path.join(userHome, '.local/share/ZeusAgent/cli/releases'))));
  const foreignHome = path.join(scratch, 'foreign');
  await mkdir(path.join(foreignHome, '.local/bin'), { recursive: true });
  await writeFile(path.join(foreignHome, '.local/bin/zeus'), '#!/bin/sh\necho user-owned\n');
  const conflict = run('bash', [installer, '--assets', assets], { env: { ...env, HOME: foreignHome, XDG_DATA_HOME: path.join(foreignHome, 'data') } });
  assert.notEqual(conflict.status, 0);
  assert.match(conflict.stderr, /different zeus command/i);
  assert.equal(await readFile(path.join(foreignHome, '.local/bin/zeus'), 'utf8'), '#!/bin/sh\necho user-owned\n');
  const editedHome = path.join(scratch, 'concurrently edited');
  const editTools = path.join(scratch, 'edit tools');
  await mkdir(path.join(editedHome, '.local/bin'), { recursive: true });
  await mkdir(editTools);
  await writeFile(path.join(editedHome, '.local/bin/zeus'), '# ZeusAgent managed CLI launcher\n');
  const cpShim = path.join(editTools, 'cp');
  await writeFile(cpShim, '#!/bin/sh\nprintf "user changed this command\\n" > "$HOME/.local/bin/zeus"\nexec /usr/bin/cp "$@"\n');
  await chmod(cpShim, 0o755);
  const edited = run('bash', [installer, '--assets', assets], { env: {
    ...env, HOME: editedHome, XDG_DATA_HOME: path.join(editedHome, 'data'), PATH: `${editTools}:${env.PATH}`,
  } });
  assert.notEqual(edited.status, 0);
  assert.match(edited.stderr, /changed during setup/i);
  assert.equal(await readFile(path.join(editedHome, '.local/bin/zeus'), 'utf8'), 'user changed this command\n');
  const tamperedHome = path.join(scratch, 'tampered');
  await mkdir(tamperedHome);
  await writeFile(packagePath, 'corrupt');
  const corrupt = run('bash', [installer, '--assets', assets], { env: { ...env, HOME: tamperedHome, XDG_DATA_HOME: path.join(tamperedHome, 'data') } });
  assert.notEqual(corrupt.status, 0);
  assert.match(corrupt.stderr, /checksum mismatch/i);
  assert.equal((await readFile(observer, 'utf8')).trim().split('\n').length, observed.length, 'corrupt archive must not execute code');
});
