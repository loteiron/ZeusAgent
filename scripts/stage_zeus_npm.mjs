/** Stage an allowlisted npm release package without copying local runtime state. */
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export async function stageNpmPackage({ manifestPath, outputDir }) {
  const output = path.resolve(outputDir);
  try {
    await mkdir(output);
  } catch (error) {
    if (error.code === 'EEXIST') throw new Error(`Output directory already exists: ${output}`);
    throw error;
  }
  const manifestText = await readFile(manifestPath, 'utf8');
  const manifest = JSON.parse(manifestText);
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(manifest.version ?? '')) {
    throw new Error('Runtime manifest must contain a valid release version.');
  }
  const template = path.join(root, 'packages/zeus-cli');
  const metadata = JSON.parse(await readFile(path.join(template, 'package.json'), 'utf8'));
  const templateVersion = metadata.version;
  metadata.version = manifest.version;
  await mkdir(path.join(output, 'bin'));
  await mkdir(path.join(output, 'lib'));
  await copyFile(path.join(template, 'bin/zeus.mjs'), path.join(output, 'bin/zeus.mjs'));
  await copyFile(path.join(root, 'scripts/windows-runtime.mjs'), path.join(output, 'lib/windows-runtime.mjs'));
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
    if (args.length !== 4 || args[0] !== '--manifest' || args[2] !== '--output') {
      throw new Error('Usage: node scripts/stage_zeus_npm.mjs --manifest <runtime-manifest.json> --output <new-directory>');
    }
    console.log(await stageNpmPackage({ manifestPath: args[1], outputDir: args[3] }));
  } catch (error) {
    console.error(`Cannot stage ZeusAgent npm package: ${error.message}`);
    process.exitCode = 2;
  }
}
