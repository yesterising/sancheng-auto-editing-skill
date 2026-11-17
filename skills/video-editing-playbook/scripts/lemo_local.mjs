#!/usr/bin/env node
// Offline Lemo readiness checks and render(t) -> frame-aligned QTRLE/ARGB.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {spawn, spawnSync} from 'node:child_process';

const HELP = `node lemo_local.mjs doctor [--lib PATH] [--tier core|full] [--report FILE.json]
node lemo_local.mjs render-alpha --project DIR --output FILE.mov --width N --height N --fps 30|30000/1001 --frames N [--start-frame N --end-frame N] [--lib PATH] [--ffmpeg PATH]`;
const home = os.homedir();
function parse(argv) {
  if (!argv.length || argv.includes('--help')) { console.log(HELP); process.exit(0); }
  const command = argv.shift();
  const allowed = command === 'doctor' ? ['lib', 'tier', 'report'] : command === 'render-alpha' ?
    ['lib', 'project', 'output', 'width', 'height', 'fps', 'frames', 'start-frame', 'end-frame', 'ffmpeg'] : [];
  if (!allowed.length) throw Error(HELP);
  const opt = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].slice(2);
    if (!argv[i].startsWith('--') || !allowed.includes(key) || !argv[i + 1] || key in opt) throw Error(HELP);
    opt[key] = argv[i + 1];
  }
  return {command, opt, lib: path.resolve(opt.lib || process.env.LEMO_OPUSCAR_HOME || path.join(home, 'lemo-opuscar'))};
}
function run(exe, args, options = {}) {
  const result = spawnSync(exe, args, {encoding: 'utf8', timeout: 60000, maxBuffer: 8 * 1024 * 1024, ...options});
  if (result.error || result.status !== 0) throw Error(`${exe}: ${result.error?.message || result.stderr?.trim() || `exit ${result.status}`}`);
  return result.stdout.trim();
}
function executable(name, explicit) {
  const candidates = explicit ? [path.resolve(explicit)] : [path.join(home, '.local/share/lemo-opuscar/bin', name),
    path.join(home, '.local/bin', name), ...(process.env.PATH || '').split(path.delimiter).map(p => path.join(p, name))];
  for (const candidate of candidates) {
    try { fs.accessSync(candidate, fs.constants.X_OK); if (fs.statSync(candidate).isFile()) return candidate; } catch {}
  }
  throw Error(`${name} not found; install/repair the local tool before rendering`);
}
async function toolkit(lib) {
  if (+process.versions.node.split('.')[0] < 20) throw Error('Node 20+ is required');
  const require = createRequire(path.join(lib, 'package.json'));
  const {chromium} = require('playwright-core');
  const browser = await import(pathToFileURL(path.join(lib, 'core/render/browser.mjs')));
  return {chromium, browser, versions: {playwright: require('playwright-core/package.json').version,
    three: JSON.parse(fs.readFileSync(path.join(lib, 'node_modules/three/package.json'))).version}};
}
function filesUnder(dir, basename, depth = 4) {
  if (depth < 0 || !fs.existsSync(dir)) return [];
  const found = [];
  for (const ent of fs.readdirSync(dir, {withFileTypes: true})) {
    const filename = path.join(dir, ent.name);
    if (ent.name === basename && fs.statSync(filename).isFile()) found.push(filename);
    else if (ent.isDirectory()) found.push(...filesUnder(filename, basename, depth - 1));
  }
  return found;
}
async function doctor(lib, opt) {
  const tier = opt.tier || 'core';
  if (!['core', 'full'].includes(tier)) throw Error('--tier must be core or full');
  const result = {schema: 'lemo-local-readiness/v1', checked_at: new Date().toISOString(), lib, tier,
    node: process.versions.node, checks: {}, extensions: {}};
  const check = async (name, fn, group = result.checks) => {
    try { group[name] = {ok: true, detail: await fn()}; } catch (e) { group[name] = {ok: false, error: e.message}; }
  };
  await check('library', () => {
    for (const file of ['AGENTS.md', 'DIRECTOR.md', 'TECHNIQUE.md', 'core/render/serve.mjs']) fs.accessSync(path.join(lib, file));
    const count = fs.readdirSync(path.join(lib, 'styles')).filter(n => !n.startsWith('_') && fs.existsSync(path.join(lib, 'styles', n, 'STYLE.md'))).length;
    if (!count) throw Error('No style prompts installed');
    return {commit: run('git', ['-C', lib, 'rev-parse', 'HEAD']), styles: count};
  });
  let tools;
  await check('node_packages', async () => { tools = await toolkit(lib); return tools.versions; });
  await check('browser_webgl2', async () => {
    if (!tools) throw Error('Node packages unavailable');
    const browser = await tools.chromium.launch({headless: true, executablePath: tools.browser.EXE, args: tools.browser.ARGS});
    try {
      const page = await browser.newPage();
      await page.route('**/*', route => route.abort());
      return await page.evaluate(() => {
        const gl = document.createElement('canvas').getContext('webgl2');
        if (!gl) throw Error('WebGL2 unavailable');
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        return {webgl2: true, renderer: gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER)};
      });
    } finally { await browser.close(); }
  });
  await check('ffmpeg', () => {
    const exe = executable('ffmpeg'), encoders = run(exe, ['-hide_banner', '-encoders']), filters = run(exe, ['-hide_banner', '-filters']);
    for (const codec of ['qtrle', 'libx264', 'aac']) if (!new RegExp(`\\b${codec}\\b`).test(encoders)) throw Error(`Missing encoder ${codec}`);
    for (const filter of ['loudnorm', 'ebur128']) if (!new RegExp(`\\b${filter}\\b`).test(filters)) throw Error(`Missing filter ${filter}`);
    return {path: exe, version: run(exe, ['-version']).split('\n')[0]};
  });
  await check('ffprobe', () => { const exe = executable('ffprobe'); return {path: exe, version: run(exe, ['-version']).split('\n')[0]}; });
  const py = path.join(lib, '.venv/bin/python');
  await check('python_core', () => run(py, ['-c', 'import sys,numpy,scipy,soundfile,soxr; from PIL import Image; assert sys.version_info >= (3,11); print(sys.version.split()[0])']));
  await check('voice_packages', () => run(py, ['-c', 'import kokoro_onnx,edge_tts,faster_whisper,av; print("kokoro_onnx edge_tts faster_whisper av imports OK")']), result.extensions);
  await check('music_package', () => run(py, ['-c', 'import numba; print(numba.__version__)']), result.extensions);
  await check('kokoro_models', () => {
    const files = ['kokoro-v1.0.onnx', 'voices-v1.0.bin'].map(n => path.join(lib, 'core/tts', n));
    for (const filename of files) if (!(fs.statSync(filename).size > 0)) throw Error(`Empty model ${filename}`);
    return files;
  }, result.extensions);
  await check('sample_libraries', () => {
    const root = path.join(lib, 'core/audio/instruments');
    fs.accessSync(path.join(root, 'index.json'));
    const libraries = ['freepats', 'karoryfer', 'salamander', 'vcsl', 'vsco2ce'];
    for (const name of libraries) if (!fs.existsSync(path.join(root, name)) || !fs.readdirSync(path.join(root, name)).length) throw Error(`Missing/empty sample library ${name}`);
    return libraries;
  }, result.extensions);
  await check('hdri', () => {
    const files = filesUnder(path.join(lib, 'core/assets/polyhaven'), 'studio_small_03_1k.hdr');
    const root = path.join(lib, 'core/assets/polyhaven');
    const hdr = fs.existsSync(root) ? fs.readdirSync(root).filter(n => /\.(hdr|exr)$/i.test(n)) : [];
    if (!files.length && !hdr.length) throw Error('No downloaded HDRI files');
    return files.length ? files : hdr;
  }, result.extensions);
  await check('whisper_models', () => {
    const cache = process.env.HF_HUB_CACHE || path.join(process.env.HF_HOME || path.join(home, '.cache/huggingface'), 'hub');
    const models = {};
    for (const name of ['base.en', 'small']) {
      models[name] = filesUnder(path.join(cache, `models--Systran--faster-whisper-${name}`, 'snapshots'), 'model.bin', 2);
      if (!models[name].length) throw Error(`Whisper ${name} not cached at ${cache}`);
    }
    return models;
  }, result.extensions);
  result.core_ready = Object.values(result.checks).every(c => c.ok);
  result.full_ready = result.core_ready && Object.values(result.extensions).every(c => c.ok);
  result.ready = tier === 'full' ? result.full_ready : result.core_ready;
  if (opt.report) {
    const file = path.resolve(opt.report); fs.mkdirSync(path.dirname(file), {recursive: true});
    fs.writeFileSync(file, JSON.stringify(result, null, 2) + '\n');
  }
  console.log(JSON.stringify(result, null, 2));
  if (!result.ready) process.exitCode = 1;
}
function integer(value, name, min = 0) {
  if (!/^\d+$/.test(value || '') || !Number.isSafeInteger(+value) || +value < min) throw Error(`--${name} must be an integer >= ${min}`);
  return +value;
}
function frameRate(value) {
  if (!/^\d+(?:\.\d+)?(?:\/\d+)?$/.test(value || '')) throw Error('--fps must be positive, e.g. 30 or 30000/1001');
  const [a, b = '1'] = value.split('/');
  const fps = +a / +b;
  if (!Number.isFinite(fps) || fps <= 0) throw Error('Invalid --fps');
  return fps;
}
async function render(lib, opt) {
  for (const name of ['project', 'output', 'width', 'height', 'fps', 'frames']) if (!opt[name]) throw Error(`Missing --${name}\n${HELP}`);
  const project = path.resolve(opt.project), output = path.resolve(opt.output);
  fs.accessSync(path.join(project, 'index.html'));
  if (path.extname(output).toLowerCase() !== '.mov') throw Error('--output must end in .mov');
  if (fs.existsSync(output)) throw Error(`Output already exists: ${output}`);
  const width = integer(opt.width, 'width', 1), height = integer(opt.height, 'height', 1), fps = frameRate(opt.fps);
  const frames = integer(opt.frames, 'frames', 1), start = integer(opt['start-frame'] || '0', 'start-frame');
  const end = integer(opt['end-frame'] || String(frames), 'end-frame', 1);
  if (!(start < end && end <= frames)) throw Error('Require 0 <= start-frame < end-frame <= frames');
  const ffmpeg = executable('ffmpeg', opt.ffmpeg), tools = await toolkit(lib);
  const {serve, pageURL} = await import(pathToFileURL(path.join(lib, 'core/render/serve.mjs')));
  let browser, server, encoder, closed, temp, complete = false, interrupted = false;
  const stop = () => {
    interrupted = true;
    encoder?.stdin.destroy(); encoder?.kill('SIGKILL');
    browser?.close().catch(() => {});
  };
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  try {
    server = await serve(lib);
    const url = pageURL(lib, server.port, project), origin = new URL(url).origin;
    browser = await tools.chromium.launch({headless: true, executablePath: tools.browser.EXE, args: tools.browser.ARGS});
    const context = await browser.newContext({viewport: {width, height}, deviceScaleFactor: 1});
    const page = await context.newPage();
    let error, rejectFailure;
    const failure = new Promise((_, reject) => { rejectFailure = reject; });
    failure.catch(() => {});
    const fail = message => { error ??= Error(message); rejectFailure(error); };
    await context.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.origin === origin || ['data:', 'blob:', 'about:'].includes(u.protocol)) return route.continue();
      fail(`External resource blocked: ${u.origin}${u.pathname}`);
      return route.abort();
    });
    page.on('pageerror', e => fail(`Page error: ${e.message}`));
    page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) fail(`Missing resource: ${r.status()} ${r.url()}`); });
    page.on('requestfailed', r => { if (!r.url().endsWith('/favicon.ico') && r.failure()?.errorText !== 'net::ERR_ABORTED') fail(`Resource failed: ${r.url()}`); });
    await Promise.race([page.goto(url, {waitUntil: 'load'}), failure]);
    await Promise.race([page.waitForFunction(() => window.READY === true, null, {timeout: 60000}), failure]);
    const duration = await Promise.race([page.evaluate(async () => {
      if (document.querySelector('video, audio')) throw Error('HTML video/audio requires a media-aware pipeline; render-alpha handles deterministic graphics');
      if (typeof window.render !== 'function') throw Error('Lemo page must implement window.render(t)');
      await document.fonts.ready;
      await Promise.all([...document.images].map(img => img.decode()));
      if (!(Number.isFinite(window.DUR) && window.DUR > 0)) throw Error('window.DUR must be a positive number');
      return window.DUR;
    }), failure]);
    const activeFrames = end - start;
    if (Math.ceil(duration * fps - 1e-9) !== activeFrames) throw Error(`window.DUR=${duration} implies ${Math.ceil(duration * fps - 1e-9)} frames, but active window is ${activeFrames}; set the page duration/timeline explicitly, without stretching`);
    const blank = await context.newPage();
    const transparentPNG = await blank.screenshot({type: 'png', omitBackground: true});
    await blank.close();
    fs.mkdirSync(path.dirname(output), {recursive: true});
    temp = path.join(path.dirname(output), `.${path.basename(output)}.partial-${process.pid}.mov`);
    encoder = spawn(ffmpeg, ['-n', '-v', 'error', '-f', 'image2pipe', '-framerate', opt.fps,
      '-vcodec', 'png', '-i', 'pipe:0', '-an', '-c:v', 'qtrle', '-pix_fmt', 'argb', temp], {stdio: ['pipe', 'ignore', 'pipe']});
    let encoderError, stderr = '';
    encoder.stderr.on('data', chunk => { stderr = (stderr + chunk.toString()).slice(-65536); });
    encoder.on('error', e => { encoderError = e; });
    encoder.stdin.on('error', e => { encoderError = e; });
    closed = new Promise(resolve => encoder.once('close', code => resolve(code)));
    for (let frame = 0; frame < frames; frame++) {
      if (interrupted) throw Error('Interrupted');
      if (error || encoderError || encoder.exitCode !== null) throw error || encoderError || Error(stderr || 'FFmpeg exited early');
      let png = transparentPNG;
      if (frame >= start && frame < end) {
        await Promise.race([page.evaluate(async t => {
          await window.render(t);
          await document.fonts.ready;
          await Promise.all([...document.images].map(img => img.decode()));
        }, (frame - start) / fps), failure]);
        if (await page.locator('video, audio').count()) throw Error('HTML video/audio is unsupported');
        png = await Promise.race([page.screenshot({type: 'png', omitBackground: true}), failure]);
      }
      await new Promise((resolve, reject) => encoder.stdin.write(png, e => e ? reject(e) : resolve()));
      if ((frame + 1) % Math.max(1, Math.round(fps * 5)) === 0) console.error(`Rendered ${frame + 1}/${frames}`);
    }
    encoder.stdin.end();
    const code = await closed;
    if (encoderError || code !== 0) throw encoderError || Error(stderr || `FFmpeg exited ${code}`);
    if (!fs.statSync(temp).size) throw Error('Empty output');
    fs.linkSync(temp, output); fs.unlinkSync(temp); temp = null; complete = true;
    console.log(JSON.stringify({schema: 'lemo-alpha-render/v1', output, project, lib, width, height,
      fps: opt.fps, frames, duration: frames / fps, start_frame: start, end_frame: end,
      page_duration: duration, codec: 'qtrle', pixel_format: 'argb', audio: false,
      page_background_preserved: true, alpha_content_verified: false, versions: tools.versions}));
  } finally {
    process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop);
    if (encoder && encoder.exitCode === null && encoder.signalCode === null) {
      encoder.stdin.destroy(); encoder.kill('SIGKILL'); await closed;
    }
    if (temp && fs.existsSync(temp)) fs.unlinkSync(temp);
    if (browser) await browser.close();
    if (server) { server.server.closeAllConnections?.(); await new Promise(resolve => server.server.close(resolve)); }
  }
  if (!complete) throw Error('Render incomplete');
}
try {
  const {command, opt, lib} = parse(process.argv.slice(2));
  if (command === 'doctor') await doctor(lib, opt); else await render(lib, opt);
} catch (e) { console.error(`lemo_local: ${e.message}`); process.exitCode = 1; }
