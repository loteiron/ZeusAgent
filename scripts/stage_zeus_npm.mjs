/** Stage an allowlisted npm release package without copying local runtime state. */
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Render the public Linux installer only after its immutable npm archive exists. */
export async function stageLinuxInstaller({ packagePath, linuxManifestPath, outputPath }) {
  const manifest = JSON.parse(await readFile(linuxManifestPath, 'utf8'));
  const node = manifest.tools?.node;
  const filename = path.basename(packagePath);
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(manifest.version ?? '')
      || !/^[a-zA-Z0-9_.-]+\.tgz$/.test(filename)
      || !node || !/^[a-f0-9]{64}$/.test(node.sha256)
      || !/^[a-zA-Z0-9_.-]+\.tar\.xz$/.test(node.file)
      || !/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*(?:\/[a-zA-Z0-9_-][a-zA-Z0-9_.-]*)+$/.test(node.executable)) {
    throw new Error('Linux installer requires a pinned release version, npm archive and Node archive identity.');
  }
  const nodeUrl = new URL(node.url);
  if (nodeUrl.protocol !== 'https:' || nodeUrl.username || nodeUrl.password) throw new Error('Node archive URL requires HTTPS without credentials.');
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(packagePath)) hash.update(chunk);
  const values = {
    VERSION: manifest.version,
    PACKAGE_FILE: filename,
    PACKAGE_URL: `https://github.com/loteiron/ZeusAgent/releases/download/v${manifest.version}/${filename}`,
    PACKAGE_SHA256: hash.digest('hex'),
    NODE_FILE: node.file, NODE_URL: node.url, NODE_SHA256: node.sha256, NODE_EXECUTABLE: node.executable,
  };
  let script = await readFile(path.join(root, 'scripts/install-linux.sh'), 'utf8');
  for (const [key, value] of Object.entries(values)) {
    // Values are inserted inside single quotes in the Bash release template.
    script = script.replaceAll(`@@ZEUS_${key}@@`, value.replaceAll("'", "'\\''"));
  }
  if (script.includes('@@ZEUS_')) throw new Error('Unresolved Linux installer template value.');
  await writeFile(outputPath, script.replaceAll('\r\n', '\n'), { flag: 'wx', mode: 0o755 });
  return path.resolve(outputPath);
}

export async function stageNpmPackage({ manifestPath, linuxManifestPath, outputDir }) {
  const manifestText = await readFile(manifestPath, 'utf8');
  const manifest = JSON.parse(manifestText);
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(manifest.version ?? '')) {
    throw new Error('Runtime manifest must contain a valid release version.');
  }
  const linuxText = linuxManifestPath ? await readFile(linuxManifestPath, 'utf8') : null;
  const linuxManifest = linuxText ? JSON.parse(linuxText) : null;
  if (linuxManifest && (linuxManifest.version !== manifest.version || linuxManifest.commit !== manifest.commit)) {
    throw new Error('Platform manifests must identify the same source commit and release version.');
  }
  const output = path.resolve(outputDir);
  try {
    await mkdir(output);
  } catch (error) {
    if (error.code === 'EEXIST') throw new Error(`Output directory already exists: ${output}`);
    throw error;
  }
  const template = path.join(root, 'packages/zeus-cli');
  const metadata = JSON.parse(await readFile(path.join(template, 'package.json'), 'utf8'));
  const templateVersion = metadata.version;
  metadata.version = manifest.version;
  // Legacy single-platform staging remains usable for its isolated Windows
  // tests; only a release carrying both manifests advertises Linux support.
  metadata.os = linuxManifest ? ['win32', 'linux'] : ['win32'];
  await mkdir(path.join(output, 'bin'));
  await mkdir(path.join(output, 'lib'));
  await copyFile(path.join(template, 'bin/zeus.mjs'), path.join(output, 'bin/zeus.mjs'));
  await copyFile(path.join(root, 'scripts/windows-runtime.mjs'), path.join(output, 'lib/windows-runtime.mjs'));
  if (linuxManifest) {
    await copyFile(path.join(root, 'scripts/linux-runtime.mjs'), path.join(output, 'lib/linux-runtime.mjs'));
    await writeFile(path.join(output, 'linux-runtime-manifest.json'), linuxText);
  }
  await copyFile(path.join(root, 'LICENSE'), path.join(output, 'LICENSE'));
  const readme = await readFile(path.join(template, 'README.md'), 'utf8');
  await writeFile(path.join(output, 'README.md'), readme.replaceAll(templateVersion, manifest.version));
  await writeFile(path.join(output, 'package.json'), `${JSON.stringify(metadata, null, 2)}\n`);
  await writeFile(path.join(output, 'runtime-manifest.json'), manifestText);
  return output;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    const options = {};
    for (let index = 0; index < args.length; index += 2) {
      const key = { '--manifest': 'manifestPath', '--linux-manifest': 'linuxManifestPath', '--output': 'outputDir' }[args[index]];
      if (!key || !args[index + 1] || options[key]) throw new Error('Invalid or duplicate staging argument.');
      options[key] = args[index + 1];
    }
    if (!options.manifestPath || !options.outputDir) throw new Error('Usage: node scripts/stage_zeus_npm.mjs --manifest <windows.json> [--linux-manifest <linux.json>] --output <new-directory>');
    console.log(await stageNpmPackage(options));
  } catch (error) {
    console.error(`Cannot stage ZeusAgent npm package: ${error.message}`);
    process.exitCode = 2;
  }
}
