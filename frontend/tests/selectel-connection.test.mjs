import test from 'node:test';
import assert from 'node:assert/strict';
import { connectionGeneration } from '../src/lib/selectelConnection.ts';

test('ordinary connection does not activate or collect', async () => {
  assert.equal(await connectionGeneration(undefined, () => assert.fail('unexpected request')), null);
  assert.equal(await connectionGeneration({ account: '29916', connection_generation: 'current' },
    () => assert.fail('unexpected request')), 'current');
});

test('lost activation response resumes the same pending review', async () => {
  const calls = [];
  const pending = { operation: 'activate', fingerprint: 'reviewed' };
  const request = async (path, body) => {
    calls.push([path, body]);
    if (path === '') return { items: [{ account: '29916', connection_generation: 'new' }] };
    return { writes_performed: true };
  };
  assert.equal(await connectionGeneration({ account: '29916', deleted: true, lifecycle_pending: pending }, request), 'new');
  assert.deepEqual(calls, [
    ['/29916/lifecycle-execute', { operation: 'activate', key: null, fingerprint: 'reviewed', confirmed: true }],
    ['', undefined],
  ]);
});

test('unconfirmed activation never supplies a generation for collection', async () => {
  const calls = [];
  await assert.rejects(connectionGeneration({ account: '29916', deleted: true }, async (path) => {
    calls.push(path);
    if (path.endsWith('lifecycle-review')) return { fingerprint: 'reviewed' };
    if (path === '') return { items: [{ account: '29916', deleted: true }] };
    return {};
  }), /ещё не подтверждено/);
  assert.deepEqual(calls, ['/29916/lifecycle-review', '/29916/lifecycle-execute', '']);
});

test('pending deletion cannot be turned into activation', async () => {
  await assert.rejects(connectionGeneration({ account: '29916', deleted: true,
    lifecycle_pending: { operation: 'delete', fingerprint: 'reviewed' } },
  () => assert.fail('unexpected request')), /Удаление ещё не подтверждено/);
});
