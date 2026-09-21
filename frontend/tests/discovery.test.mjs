import assert from 'node:assert/strict';
import test from 'node:test';
import { runDiscovery, validDiscovery } from '../src/api/discovery.ts';

const result = { source_instance: 'pve-test', source_type: 'proxmox', site_slug: 'test',
  cluster_name: 'Test', items: [{ object_kind: 'qemu', name: 'vm', external_id: '100',
    classification: 'IGNORED', reason_code: 'POLICY_FUTURE', reason: 'Visible ignored item',
    future_action: 'ignored', matched_object_id: null, matched_object_name: null }] };

test('discovery client sends protected POST and preserves visible classifications', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json(result));
  assert.deepEqual(await runDiscovery('pve-test', new AbortController().signal), result);
  const [path, options] = mock.mock.calls[0].arguments;
  assert.equal(path, '/api/v1/sources/pve-test/discovery');
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-NetBox-Sync-CSRF'], 'same-origin');
});

test('discovery client rejects malformed result and reports stable errors', async (context) => {
  const mock = context.mock.method(globalThis, 'fetch', async () => Response.json({ ...result,
    items: [{ ...result.items[0], classification: ['IGNORED'] }] }));
  await assert.rejects(runDiscovery('pve-test', new AbortController().signal), /malformed/);
  mock.mock.mockImplementation(async () => Response.json({ error: { code: 'SOURCE_DISABLED' } }, { status: 409 }));
  await assert.rejects(runDiscovery('pve-test', new AbortController().signal), /Disabled/);
});

test('discovery failures distinguish provider and registry without exposing raw errors', async context => {
  const mock = context.mock.method(globalThis,'fetch');
  for (const [code,message] of [['PROVIDER_UNAVAILABLE','Source discovery is unavailable.'],['REGISTRY_UNAVAILABLE','Discovery registry is unavailable.']]) {
    mock.mock.mockImplementationOnce(async()=>Response.json({error:{code,message:'RAW SECRET'}},{status:503}));
    await assert.rejects(runDiscovery('pve-test',new AbortController().signal),error=>error.message===message);
  }
});


test('hardware transport rejects malformed lists before rendering',()=>{
  const withProperties=p=>({...result,items:[{...result.items[0],properties:p}]});
  assert.equal(validDiscovery(withProperties({vcpus:4,addresses:['192.0.2.7'],interfaces:[{name:'eth0',addresses:[]}],disks:[]}), 'pve-test'),true);
  for(const properties of [null,{addresses:3},{interfaces:[{name:'eth0',addresses:null}]},{disks:[{name:'disk0',size_bytes:'8'}]},{memory_bytes:-1}])
    assert.equal(validDiscovery(withProperties(properties),'pve-test'),false);
});
