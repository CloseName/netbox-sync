import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {ru} from '../src/ui/ru.ts';
import {tr} from '../src/ui/i18n.ts';
import {setLanguage} from '../src/ui/language.ts';
import {health,runStates,scheduleStates} from '../src/ui/status.ts';
import {navigation} from '../src/ui/routes.ts';
import {fieldText} from '../src/ui/plan.ts';
test('every explicit UI translation key and closed operational label has RU copy',()=>{
 for(const file of fs.readdirSync('src',{recursive:true}).filter(f=>f.endsWith('.tsx'))){
  const text=fs.readFileSync('src/'+file,'utf8');
  for(const match of text.matchAll(/\btr\((["'])(.*?)\1\)/g))assert.ok(Object.hasOwn(ru,match[2]),file+': '+match[2]);
 }
 for(const {label} of [...Object.values(health),...Object.values(runStates),...Object.values(scheduleStates),...navigation])assert.ok(Object.hasOwn(ru,label),label);
});
test('language formats authored text, never managed values or prototype keys',()=>{
 setLanguage('ru');
 try {assert.equal(tr('Runs'),'Запуски');assert.equal(tr('toString'),'toString');assert.equal(fieldText({provided:true,value:'Saved'}),'Saved');}
 finally {setLanguage('en');}
 assert.equal(tr('Runs'),'Runs');
});
