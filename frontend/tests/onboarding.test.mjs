import assert from 'node:assert/strict';
import test from 'node:test';
import { testConnection, registerSource, SourceIdReservedError, SourceConnectionError, RegistrationFailure, HostRegistrationFailure } from '../src/api/onboarding.ts';

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
  await assert.rejects(registerSource({ confirm_sync_disabled: true }), error=>error instanceof RegistrationFailure&&error.uncertain);
});

test('reserved identity has a typed safe error while unknown conflict text stays hidden', async (context) => {
  const mock=context.mock.method(globalThis,'fetch',async()=>Response.json({error:{code:'SOURCE_ID_RESERVED',message:'SECRET_SENTINEL'}},{status:409}));
  await assert.rejects(registerSource({confirm_sync_disabled:true}),error=>error instanceof SourceIdReservedError && !error.message.includes('SENTINEL'));
  mock.mock.mockImplementation(async()=>Response.json({error:{code:'SECRET_SENTINEL',message:'SECRET_SENTINEL'}},{status:409}));
  await assert.rejects(registerSource({confirm_sync_disabled:true}),error=>!(error instanceof SourceIdReservedError) && !error.message.includes('SENTINEL'));
});

for (const code of ['SOURCE_CONNECTION_FAILED', 'SOURCE_TIMEOUT', 'SOURCE_TLS_FAILED', 'SOURCE_AUTH_FAILED', 'SOURCE_DESTINATION_DENIED']) {
 test(`connection error ${code} is typed and redacted`, async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({error: {code, message: 'REMOTE_SECRET'}}, {status: 422}));
  await assert.rejects(testConnection({}), error => error instanceof SourceConnectionError && error.code === code && !error.message.includes('REMOTE_SECRET'));
 });
}
test('unknown remote codes and prototype keys cannot become UI messages', async (context) => {
 const fetch = context.mock.method(globalThis, 'fetch', async () => new Response(''));
 for (const code of ['REMOTE_SECRET', '__proto__', 'constructor']) {
  fetch.mock.mockImplementation(async () => Response.json({error: {code, message: 'REMOTE_SECRET'}}, {status: 502}));
  await assert.rejects(testConnection({}), error => !(error instanceof SourceConnectionError) && !error.message.includes('REMOTE_SECRET'));
 }
});

for(const code of ['ONBOARDING_TOKEN_INVALID','PROBE_RECEIPT_INVALID'])test(`registration expiry ${code} is confirmed refusal`,async context=>{
 context.mock.method(globalThis,'fetch',async()=>Response.json({error:{code,message:'REMOTE_PRIVATE'}},{status:409}));
 await assert.rejects(registerSource({confirm_sync_disabled:true}),error=>error instanceof RegistrationFailure&&error.code===code&&!error.uncertain);
});
test('registration transport failure stays uncertain and never retries',async context=>{
 let calls=0;context.mock.method(globalThis,'fetch',async()=>{calls++;throw new Error('REMOTE_PRIVATE');});
 await assert.rejects(registerSource({confirm_sync_disabled:true}),error=>error instanceof RegistrationFailure&&error.uncertain&&!error.message.includes('REMOTE_PRIVATE'));
 assert.equal(calls,1);
});


test('host duplicate errors preserve only a validated source link and local copy',async(context)=>{
 context.mock.method(globalThis,'fetch',async()=>Response.json({error:{code:'HOST_ALREADY_REGISTERED',existing_source:'source-existing',message:'untrusted remote text',source_url:'https://untrusted.invalid'}},{status:409}));
 await assert.rejects(testConnection({source_type:'esxi',address:'alias.test',verify_ssl:true,username:'fixture',secret:'fixture'}),error=>error instanceof HostRegistrationFailure&&error.source==='source-existing'&&error.message==='HOST_ALREADY_REGISTERED');
});

test('conflict details accept only bounded source IDs and closed states',async context=>{
 context.mock.method(globalThis,'fetch',async()=>Response.json({error:{code:'HOST_IDENTITY_CONFLICT',conflicts:[{source_instance:'source-one',state:'REMOVED',secret:'discard'},{source_instance:'https://bad.invalid',state:'REGISTERED'},{source_instance:'source-two',state:'UNTRUSTED'}]}},{status:409}));
 await assert.rejects(testConnection({}),error=>error instanceof HostRegistrationFailure&&JSON.stringify(error.conflicts)===JSON.stringify([{source_instance:'source-one',state:'REMOVED'}]));
});
