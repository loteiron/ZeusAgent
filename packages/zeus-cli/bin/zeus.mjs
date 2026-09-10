#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, realpathSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const desktopKey = 'HKCU\\Software\\ZeusAgent\\DesktopCLI';

function run(command, args, env = process.env) {
  // npm owns the CMD/PowerShell shims. All subsequent argument transport bypasses
  // the shell, and the user's project directory survives the runtime bootstrap.
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: process.cwd(), stdio: 'inherit', shell: false, env });
    const interrupt = () => {
      // Windows console control events already reach the child. Node's kill
      // would terminate the bootstrap before it can stop its Python process.
      if (process.platform !== 'win32' && !process.stdin.isTTY) child.kill('SIGINT');
    };
    const terminate = () => child.kill('SIGTERM');
    process.on('SIGINT', interrupt);
    process.on('SIGTERM', terminate);
    const cleanup = () => { process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', terminate); };
    child.on('error', error => { cleanup(); reject(error); });
    child.on('close', (code, signal) => {
      cleanup();
      resolve(code ?? (signal === 'SIGINT' ? 130 : 1));
    });
  });
}

export async function launchLinuxDesktop(args, executable = '/opt/ZeusAgent/ZeusAgent') {
  if (!existsSync(executable)) throw new Error('Install the ZeusAgent desktop .deb from https://github.com/loteiron/ZeusAgent/releases.');
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ZEUS_DESKTOP_RESOURCES;
  return run(executable, args, env);
}

export async function launchDesktop(args, registryKey = desktopKey) {
  if (process.platform === 'linux') return launchLinuxDesktop(args);
  const hint = 'Install the ZeusAgent desktop setup.exe from https://github.com/loteiron/ZeusAgent/releases.';
  const scratch = mkdtempSync(path.join(tmpdir(), 'zeus-desktop-location-'));
  const exported = path.join(scratch, 'location.reg');
  let executable;
  try {
    // Registry exports are UTF-16; `reg query` depends on the active code page
    // and corrupts a non-ASCII installation path on many Windows installations.
    const reg = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32/reg.exe');
    const result = spawnSync(reg, ['export', registryKey, exported, '/y'], {
      timeout: 10_000, windowsHide: true, stdio: 'ignore', shell: false,
    });
    if (result.error || result.status !== 0) throw new Error(hint);
    const match = readFileSync(exported, 'utf16le').match(/^"InstallDirectory"="(.*)"\r?$/m);
    const directory = match?.[1].replace(/\\(["\\])/g, '$1');
    if (!directory || !path.isAbsolute(directory)) throw new Error(hint);
    executable = path.join(directory, 'ZeusAgent.exe');
    if (!existsSync(executable)) throw new Error(hint);
  } finally {
    if (existsSync(exported)) unlinkSync(exported);
    rmdirSync(scratch);
  }
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.ZEUS_DESKTOP_RESOURCES;
  return run(executable, args, env);
}

export async function main(args = process.argv.slice(2)) {
  if (!['win32', 'linux'].includes(process.platform) || process.arch !== 'x64') {
    throw new Error('This ZeusAgent release supports Windows x64 and Linux x64.');
  }
  if (args[0] === '--desktop') return launchDesktop(args.slice(1));
  // Only the desktop installer shim supplies this bridge to bundled Electron.
  // A normal npm/Node invocation always uses its own release manifest.
  const resources = process.versions.electron && process.env.ZEUS_DESKTOP_RESOURCES;
  const helper = process.platform === 'linux' ? 'linux-runtime.mjs' : 'windows-runtime.mjs';
  const runtime = resources
    ? path.join(resources, 'backend', helper)
    : path.join(packageRoot, 'lib', helper);
  const manifest = resources
    ? path.join(resources, 'backend/runtime-manifest.json')
    : path.join(packageRoot, process.platform === 'linux' ? 'linux-runtime-manifest.json' : 'runtime-manifest.json');
  if (!existsSync(runtime) || !existsSync(manifest)) {
    throw new Error('ZeusAgent package is incomplete. Reinstall the npm release package or desktop installer.');
  }
  return run(process.execPath, [runtime, '--manifest', manifest, '--', ...args]);
}

function isMainModule() {
  if (!process.argv[1]) return false;
  try {
    // npm's POSIX bin is a symlink. Node resolves the module URL but retains
    // the invoked link in argv, so both sides must use their actual file path.
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    // Importing the launcher from an eval or a removed caller must stay inert.
    return false;
  }
}

if (isMainModule()) {
  try {
    process.exitCode = await main();
  } catch (error) {
    console.error(`ZeusAgent could not start: ${error.message}`);
    process.exitCode = 2;
  }
}
