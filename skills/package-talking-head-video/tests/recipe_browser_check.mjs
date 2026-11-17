// Optional real-browser regression check. Fixtures and outputs stay in the task work directory.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL,fileURLToPath} from 'node:url';

const opt={};for(let i=2;i<process.argv.length;i+=2)opt[process.argv[i].slice(2)]=process.argv[i+1];
for(const k of ['cases','out-dir','playwright-from'])assert(opt[k],'Missing --'+k);
const root=path.resolve(opt['out-dir']),skill=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
assert(!root.startsWith(path.dirname(skill)+path.sep),'Use project work for artifacts');
fs.mkdirSync(root,{recursive:false});
const cases=JSON.parse(fs.readFileSync(opt.cases)),require=createRequire(path.resolve(opt['playwright-from']));
let chromium;try{({chromium}=require('playwright'))}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;({chromium}=require('playwright-core'))}
const browser=await chromium.launch({headless:true,executablePath:opt.browser});
const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),results=[];
try{
 for(let i=0;i<cases.length;i++){
  const c=cases[i],d=c.data,page=await browser.newPage({viewport:{width:d.width,height:d.height}});
  await page.route('**/*',r=>['file:','data:','blob:','about:'].includes(new URL(r.request().url()).protocol)?r.continue():r.abort());
  await page.goto(pathToFileURL(c.html).href);await page.evaluate(async()=>{await window.ready;await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()))});
  const points=[...new Set([0,d.frames-1,...Object.values(d.events).flatMap(f=>[f-1,f,f+1])])].filter(f=>f>=0&&f<d.frames).sort((a,b)=>a-b);
  for(const f of points){
   await page.evaluate(t=>window.renderAt(t),f/d.fps);
   const info=await page.evaluate(()=>({layout:window.layoutReport,
    active:[...document.querySelectorAll('.chip')].map(e=>e.dataset.active),
    colors:[...document.querySelectorAll('.chip')].map(e=>[getComputedStyle(e).color,getComputedStyle(e).backgroundColor]),
    opacity:[...document.querySelectorAll('.chip')].map(e=>Number(getComputedStyle(e).opacity)),
    paths:[...document.querySelectorAll('path')].map(e=>Number(getComputedStyle(e).opacity)),
    outlines:[...document.querySelectorAll('.label,.chip')].map(e=>parseFloat(getComputedStyle(e).webkitTextStrokeWidth))}));
   assert(info.outlines.every(v=>v>=.5),'Solid outline missing');
   if(d.recipe==='process-flow'&&d.params.step_events){
    assert.deepEqual(info.active,d.params.step_events.map(id=>String(f>=d.events[id])));
    for(let j=0;j<info.colors.length;j++)if(info.active[j]==='true')assert.notEqual(...info.colors[j],'Active text blends into its background');
   }
   if(d.recipe==='path-converge'&&f>=d.events[d.params.merge_events[1]]){
    assert.equal(info.opacity.at(-1),1);assert(info.opacity.slice(0,-1).every(v=>v===0));assert(info.paths.every(v=>v===0));
   }
   if(f===d.frames-1)await page.screenshot({path:path.join(root,'case-'+i+'.png'),omitBackground:true});
  }
  const mid=Math.floor(d.frames/2);await page.evaluate(t=>window.renderAt(t),mid/d.fps);const a=await page.screenshot({omitBackground:true});
  await page.evaluate(t=>window.renderAt(t),(d.frames-1)/d.fps);await page.evaluate(t=>window.renderAt(t),mid/d.fps);
  assert.equal(hash(a),hash(await page.screenshot({omitBackground:true})),'Same frame changes after seeking');
  results.push({recipe:d.recipe,size:[d.width,d.height],frames:points,layout:await page.evaluate(()=>window.layoutReport)});
  await page.close();
 }
 const original=cases.find(c=>c.data.recipe==='impact-title').data,template=fs.readFileSync(path.join(skill,'assets/scene-template.html'),'utf8');
 for(const [name,title,size] of [['long-title','过长中文网址'.repeat(16),50],['too-tall','字',original.height*.8]]){
  const d=structuredClone(original);d.params.title=title;d.params.font_size=size;
  const file=path.join(root,name+'.html');fs.writeFileSync(file,template.replace('__SCENE_DATA__',JSON.stringify(d).replaceAll('<','\\u003c')));
  const page=await browser.newPage({viewport:{width:d.width,height:d.height}});await page.goto(pathToFileURL(file).href);await page.evaluate(async()=>{await window.ready;await document.fonts.ready});
  await assert.rejects(()=>page.evaluate(()=>window.renderAt(0)),/Text does not fit/);await page.close();
 }
 fs.writeFileSync(path.join(root,'results.json'),JSON.stringify({ok:true,cases:results,overflow_rejected:true},null,2));
 console.log(JSON.stringify({ok:true,cases:results.length,overflow_rejected:true}));
}finally{await browser.close()}
