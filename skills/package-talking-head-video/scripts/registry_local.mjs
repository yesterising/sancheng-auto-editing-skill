#!/usr/bin/env node
// Deliberately exposes only the free component catalogue and source download.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

const skillRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const runtime = path.resolve(skillRoot, '../hyperframes-registry/runtime/node_modules/hyperframes');
const usage = 'registry_local.mjs search "English effect query" | add ITEM --dir PROJECT_DIR';
function main() {
  const [command, value, ...rest] = process.argv.slice(2);
  if (command === '--help') { console.log(usage); return; }
  if (!['search', 'add'].includes(command) || !value || value.startsWith('-')) throw Error(usage);
  const manifest = JSON.parse(fs.readFileSync(path.join(runtime, 'package.json'), 'utf8'));
  if (manifest.version !== '0.8.186') throw Error('Pinned registry runtime changed; validate the upgrade before use');
  let args;
  if (command === 'search') {
    if (rest.length) throw Error(usage);
    args = ['catalog', '--query', value, '--json'];
  } else {
    if (rest.length !== 2 || rest[0] !== '--dir' || !/^[a-z0-9-]+$/.test(value)) throw Error(usage);
    const dir = path.resolve(rest[1]);
    const skills = path.resolve(skillRoot, '..');
    if (dir === skills || dir.startsWith(skills + path.sep)) throw Error('Download project components into the task work/ directory');
    fs.mkdirSync(dir, {recursive: true});
    args = ['add', value, '--dir', dir, '--no-clipboard', '--json'];
  }
  const result = spawnSync(process.execPath, [path.join(runtime, manifest.bin.hyperframes), ...args], {
    stdio: 'inherit', env: {...process.env, HYPERFRAMES_SKIP_SKILLS: '1'},
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
}
try { main(); } catch (error) { console.error(JSON.stringify({ok: false, error: error.message})); process.exitCode = 2; }
