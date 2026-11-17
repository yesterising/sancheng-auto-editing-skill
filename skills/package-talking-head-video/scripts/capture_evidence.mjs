#!/usr/bin/env node
// One real screenshot and its measured targets; local files only, no installation or editor control.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

const help='node capture_evidence.mjs --url URL --targets selectors.json --out-dir NEW_DIR --playwright-from EXISTING/package.json [--browser EXISTING_CHROMIUM] [--ffmpeg EXISTING_FFMPEG] [--width 1280] [--height 900] [--dpr 2]';
const opts={};
try {
 const args=process.argv.slice(2);
 if(args.includes('--help')){console.log(help);process.exit(0)}
 for(let i=0;i<args.length;i+=2){const key=args[i].slice(2);if(!args[i].startsWith('--')||!['url','targets','out-dir','playwright-from','browser','ffmpeg','width','height','dpr'].includes(key)||!args[i+1]||key in opts)throw Error(help);opts[key]=args[i+1]}
 for(const key of ['url','targets','out-dir','playwright-from'])if(!opts[key])throw Error('Missing --'+key);
 const url=new URL(opts.url);if(!['http:','https:','file:'].includes(url.protocol)||url.username||url.password)throw Error('Use an explicit HTTP(S) or local file URL without embedded credentials');
 const width=Number(opts.width||1280),height=Number(opts.height||900),dpr=Number(opts.dpr||2);
 if(![width,height].every(v=>Number.isInteger(v)&&v>0)||!Number.isFinite(dpr)||dpr<=0||dpr>4)throw Error('Invalid viewport or DPR');
 const targets=JSON.parse(fs.readFileSync(opts.targets,'utf8'));
 if(!targets||Array.isArray(targets)||!Object.keys(targets).length||Object.entries(targets).some(([k,v])=>!/^[-a-zA-Z0-9_]+$/.test(k)||typeof v!=='string'||!v.trim()))throw Error('targets.json must map safe target IDs to unique selectors');
 const out=path.resolve(opts['out-dir']),skills=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
 if(out===skills||out.startsWith(skills+path.sep))throw Error('Capture artifacts belong in the task work directory');
 if(fs.existsSync(out))throw Error('Output directory already exists; choose a new version');
 const require=createRequire(path.resolve(opts['playwright-from']));let chromium;
 try{({chromium}=require('playwright'))}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;({chromium}=require('playwright-core'))}
 const browser=await chromium.launch({headless:true,executablePath:opts.browser?path.resolve(opts.browser):undefined,args:['--allow-file-access-from-files']});
 try{
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:dpr});
  await page.goto(url.href,{waitUntil:'load',timeout:45000});
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()))});
  const measure=async()=>{
   const boxes={};
   for(const [id,selector] of Object.entries(targets)){
    const locator=page.locator(selector);
    if(await locator.count()!==1)throw Error('Target must resolve exactly once: '+id);
    boxes[id]=await locator.evaluate(e=>{const r=e.getBoundingClientRect();return [r.x+scrollX,r.y+scrollY,r.width,r.height]});
   }
   return {boxes,size:await page.evaluate(()=>[Math.max(innerWidth,document.documentElement.scrollWidth),Math.max(innerHeight,document.documentElement.scrollHeight)])};
  };
  const before=await measure(),png=await page.screenshot({fullPage:true,animations:'disabled'}),after=await measure();
  if(JSON.stringify(before)!==JSON.stringify(after))throw Error('Page geometry changed during capture; capture a stable state');
  const pw=png.readUInt32BE(16),ph=png.readUInt32BE(20),sx=pw/before.size[0],sy=ph/before.size[1],pixels={};
  for(const [id,[x,y,w,h]] of Object.entries(before.boxes)){
   if(w<=0||h<=0||x<0||y<0||x+w>before.size[0]||y+h>before.size[1])throw Error('Target outside captured document: '+id);
   pixels[id]=[x*sx,y*sy,w*sx,h*sy];
  }
  fs.mkdirSync(out,{recursive:true});const image=path.join(out,'page.png');fs.writeFileSync(image,png,{flag:'wx'});
  const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),slices={};
  if(opts.ffmpeg)for(const [id,[x,y,w,h]] of Object.entries(pixels)){
   const box=[Math.floor(x),Math.floor(y),Math.ceil(x+w)-Math.floor(x),Math.ceil(y+h)-Math.floor(y)],file=path.join(out,id+'.png');
   const r=spawnSync(path.resolve(opts.ffmpeg),['-n','-v','error','-i',image,'-vf',`crop=${box[2]}:${box[3]}:${box[0]}:${box[1]}`,'-frames:v','1',file],{encoding:'utf8',timeout:30000});
   if(r.error||r.status!==0)throw Error(r.error?.message||r.stderr);
   slices[id]={path:file,rect:box,sha256:hash(fs.readFileSync(file))};
  }
  const result={schema:'sancheng-evidence/v1',image_sha256:hash(png),width:pw,height:ph,targets:pixels,
   source:{url:url.href,viewport:[width,height],page_css:before.size,device_scale_factor:dpr,targets_css:before.boxes,coordinate_system:'full screenshot pixels; CSS page origin (0,0)'},slices};
  fs.writeFileSync(path.join(out,'geometry.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({image,geometry:path.join(out,'geometry.json'),targets:Object.keys(pixels),status:'captured_not_reviewed'}));
 }finally{await browser.close()}
}catch(error){console.error(JSON.stringify({ok:false,error:error.message}));process.exitCode=2}
