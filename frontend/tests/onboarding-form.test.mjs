import assert from 'node:assert/strict';
import test from 'node:test';
import Module from 'node:module';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { buildSync } from 'esbuild';

// Use the existing Vite/esbuild toolchain and inspect React elements, not a new DOM framework.
const filename = fileURLToPath(import.meta.url);
const compiled = buildSync({
  entryPoints: [fileURLToPath(new URL('../src/pages/AddSourcePage.tsx', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false, external: ['react', 'react/jsx-runtime'],
}).outputFiles[0].text;
const componentModule = new Module(filename);
componentModule.filename = filename;
componentModule.paths = Module._nodeModulePaths(fileURLToPath(new URL('..', import.meta.url)));
componentModule._compile(compiled, filename);
const { AddSourcePage } = componentModule.exports;

function elements(node) {
  if (Array.isArray(node)) return node.flatMap(elements);
  if (!node || typeof node !== 'object') return [];
  return [node, ...elements(node.props?.children)];
}

function setup(context) {
  context.mock.method(React, 'useSyncExternalStore', (_subscribe,snapshot) => snapshot());
  context.mock.method(React, "useRef", () => ({current: null}));
  context.mock.method(React, "useEffect", () => {});
  const state = [];
  let cursor = 0;
  context.mock.method(React, 'useState', (initial) => {
    const index = cursor++;
    if (!(index in state)) state[index] = initial;
    return [state[index], (value) => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
  });
  context.mock.method(globalThis, 'FormData', function FormData(form) { return form.data; });
  return { state, render() { cursor = 0; return elements(AddSourcePage()); } };
}

function event(values) {
  const data = new Map(Object.entries(values));
  return { preventDefault() {}, currentTarget: { data, cleared: false, reset() {
    this.cleared = true;
    for (const key of ['username', 'secret', 'token_id']) this.data.delete(key);
  } } };
}

test('source type changes clear credential form and ESXi has no token field', (context) => {
  const app = setup(context);
  assert.ok(app.render().some((element) => element.props?.name === 'token_id'));
  let cleared = false;
  app.render().find((element) => element.type === 'select').props.onChange({
    target: { value: 'esxi' }, currentTarget: { form: { reset() { cleared = true; } } },
  });
  assert.equal(cleared, true);
  assert.ok(!app.render().some((element) => element.props?.name === 'token_id'));
});

test('test-review-confirm-register clears credentials and keeps sync disabled', async (context) => {
  const app = setup(context);
  let calls = 0;
  const source = {
    source_instance: 'new-source', type: 'proxmox', name: 'New', address: 'source.test',
    enabled: true, sync_enabled: false, verify_ssl: true, sync_interval_seconds: 600,
    site_slug: 'test', cluster_name: 'Test', platform_slug: 'pve', device_role_slug: 'host',
    device_type_slug: 'server', cluster_type_slug: 'pve', legacy_identity_owner: false, status: 'sync_disabled',
  };
  context.mock.method(globalThis, 'fetch', async (_path, options) => {
    calls++;
    const input = JSON.parse(options.body);
    if (calls === 1) {
      assert.equal(input.secret, 'FAKE_SECRET');
      return Response.json({ status: 'success', onboarding_token: 'opaque-token-0123456789abcdef' });
    }
    assert.equal(input.confirm_sync_disabled, true);
    assert.ok(!('secret' in input));
    return Response.json(source);
  });
  const connectionEvent = event({ username: 'user@realm', token_id: 'token', secret: 'FAKE_SECRET' });
  await app.render().find((element) => element.type === 'form').props.onSubmit(connectionEvent);
  assert.equal(connectionEvent.currentTarget.cleared, true);
  assert.ok(!JSON.stringify(app.state).includes('FAKE_SECRET'));
  assert.ok(!app.render().some((element) => element.props?.name === 'secret'));
  const registration = { ...source, interval: '600' };
  await app.render().find((element) => element.type === 'form').props.onSubmit(event(registration));
  assert.equal(calls, 1, 'No registration before confirmation');
  await app.render().find((element) => element.type === 'form').props.onSubmit(event({ ...registration, confirm: 'on' }));
  assert.equal(calls, 2);
  assert.ok(app.render().some((element) => element.props?.title === 'Source registered'));
  assert.ok(!JSON.stringify(app.state).includes('opaque-token'));
});

test('failed connection test clears credentials and cannot reach registration', async (context) => {
  const app = setup(context);
  context.mock.method(globalThis, 'fetch', async () => new Response('RAW_SECRET_ERROR', { status: 422 }));
  const input = event({ username: 'user@realm', token_id: 'token', secret: 'FAKE_SECRET' });
  await app.render().find((element) => element.type === 'form').props.onSubmit(input);
  assert.equal(input.currentTarget.cleared, true);
  assert.ok(app.render().some((element) => element.props?.role === 'alert'));
  assert.ok(!app.render().some((element) => element.props?.name === 'confirm'));
  assert.ok(!JSON.stringify(app.state).includes('RAW_SECRET_ERROR'));
});

test('in-flight connection controls locked and changing tested values requires re-test', async (context) => {
  const app = setup(context);
  let finish;
  context.mock.method(globalThis, 'fetch', (path) => path.endsWith('/cancel-onboarding')
    ? Promise.resolve(Response.json({ status: 'cancelled' }))
    : new Promise((resolve) => { finish = resolve; }));
  const input = event({ username: 'user@realm', token_id: 'token', secret: 'FAKE_SECRET' });
  const pending = app.render().find((element) => element.type === 'form').props.onSubmit(input);
  const busyTree = app.render();
  const fieldset = busyTree.find((element) => element.type === 'fieldset');
  assert.equal(fieldset.props.disabled, true);
  assert.ok(elements(fieldset).some((element) => element.type === 'select'));
  assert.ok(elements(fieldset).some((element) => element.props?.name === 'secret'));
  assert.ok(elements(fieldset).some((element) => element.type === 'input' && element.props.type === 'checkbox'));
  finish(Response.json({ status: 'success', onboarding_token: 'opaque-token-0123456789abcdef' }));
  await pending;
  assert.ok(JSON.stringify(app.state).includes('opaque-token'));
  await app.render().find((element) => element.type === 'button' && element.props.type === 'button').props.onClick();
  assert.ok(!JSON.stringify(app.state).includes('opaque-token'));
  assert.ok(app.render().some((element) => element.props?.name === 'secret'));
  assert.ok(!app.render().some((element) => element.props?.name === 'confirm'));
});
