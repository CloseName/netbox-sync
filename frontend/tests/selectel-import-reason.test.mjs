import test from 'node:test';
import assert from 'node:assert/strict';
import {selectelImportReason} from '../src/pages/selectelImportReason.ts';
test('import reasons explain validation and never echo unknown remote text',()=>{
 assert.match(selectelImportReason('OBJECT_VALIDATION'),/Поля объекта/);
 assert.match(selectelImportReason('DATABASE_CONSTRAINT'),/базы данных/);
 assert.ok(!selectelImportReason('PRIVATE remote error').includes('PRIVATE'));
});
