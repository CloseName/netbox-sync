
import test from 'node:test';
import assert from 'node:assert/strict';
import Module from 'node:module';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {buildSync} from 'esbuild';
const filename=fileURLToPath(import.meta.url), module=new Module(filename);
module.filename=filename;module.paths=Module._nodeModulePaths(fileURLToPath(new URL('..',import.meta.url)));
module._compile(buildSync({stdin:{contents:"export {OperationFeedback} from './src/ui/OperationFeedback'; export {setLanguage} from './src/ui/language';",resolveDir:fileURLToPath(new URL('..',import.meta.url)),loader:'ts'},bundle:true,platform:'node',format:'cjs',write:false,external:['react','react/jsx-runtime']}).outputFiles[0].text,filename);
test('operation feedback separates acknowledgement, running, completed and unknown in EN/RU',t=>{
 t.mock.method(React,'useSyncExternalStore',(_s,snapshot)=>snapshot());
 t.mock.method(React,'useState',()=>[Date.now(),()=>{}]);
 t.mock.method(React,'useEffect',()=>{});
 const {OperationFeedback,setLanguage}=module.exports;
 for(const lang of ['en','ru']){
  setLanguage(lang);
  const copy=lang==='en'?['Waiting for server acknowledgement','Operation in progress','Operation completed','Outcome unknown']:['Ожидаем подтверждение сервера','Операция выполняется','Операция завершена','Результат неизвестен'];
  ['sending','running','completed','uncertain'].forEach((phase,index)=>{
   const html=renderToStaticMarkup(OperationFeedback({operation:'Plan',phase,started:Date.now()-5000}));
   assert.ok(html.includes(copy[index]));
   assert.equal(html.includes('activity-indicator'),index<2);
   assert.equal(html.includes('Elapsed')||html.includes('Прошло'),index<2);
   assert.doesNotMatch(html,/Connection lost|Связь потеряна/);
  });
 }
 setLanguage('en');
});
