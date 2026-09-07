import assert from 'node:assert/strict';
import test from 'node:test';
import { testConnection, registerSource, SourceIdReservedError } from '../src/api/onboarding.ts';

test('Test Connection sends credentials only in protected JSON and validates token', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/v1/sources/test-connection');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['X-NetBox-Sync-CSRF'], 'same-origin');
    assert.equal(JSON.parse(options.body).secret, 'fake-test-value');
    return Response.json({ status: 'success', onboarding_token: 'opaque-token-0123456789abcdef' });
  });
  const input = { source_type: 'esxi', address: 'test', verify_ssl: true, username: 'user', secret: 'fake-test-value' };
  assert.equal(await testConnection(input), 'opaque-token-0123456789abcdef');
  mock.mock.mockImplementation(async () => Response.json({ status: 'success', onboarding_token: ['invalid'] }));
  await assert.rejects(testConnection(input), /Unsupported/);
  mock.mock.mockImplementation(async () => new Response('secret-backend-error', { status: 422 }));
  await assert.rejects(testConnection(input), (error) => !error.message.includes('secret-backend-error'));
});

test('registration requires confirmation and rejects sync-enabled results', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ sync_enabled: true }));
  await assert.rejects(registerSource({ confirm_sync_disabled: false }), /confirmation/);
  await assert.rejects(registerSource({ confirm_sync_disabled: true }), /Unexpected registration/);
});

test('reserved identity has a typed safe error while unknown conflict text stays hidden', async (context) => {
  const mock=context.mock.method(globalThis,'fetch',async()=>Response.json({error:{code:'SOURCE_ID_RESERVED',message:'SECRET_SENTINEL'}},{status:409}));
  await assert.rejects(registerSource({confirm_sync_disabled:true}),error=>error instanceof SourceIdReservedError && !error.message.includes('SENTINEL'));
  mock.mock.mockImplementation(async()=>Response.json({error:{code:'SECRET_SENTINEL',message:'SECRET_SENTINEL'}},{status:409}));
  await assert.rejects(registerSource({confirm_sync_disabled:true}),error=>!(error instanceof SourceIdReservedError) && !error.message.includes('SENTINEL'));
});
