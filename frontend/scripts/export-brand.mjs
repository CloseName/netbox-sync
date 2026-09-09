// Reproducible raster exports of our native SVG mark, using the existing browser toolchain.
import {chromium} from '@playwright/test';
import {readFileSync} from 'node:fs';
const root='public/assets/brand';
const svg=readFileSync(root+'/mark.svg','utf8');
const browser=await chromium.launch();
try {const page=await browser.newPage({deviceScaleFactor:1});
 for(const size of [16,32,180]){
  await page.setViewportSize({width:size,height:size});
  await page.setContent('<style>html,body{margin:0;background:transparent}svg{width:100vw;height:100vh;display:block}</style>'+svg);
  await page.screenshot({path:root+'/icon-'+size+'.png',omitBackground:true});
 }
} finally {await browser.close();}
