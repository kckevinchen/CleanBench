import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../frontend/labeling/shared/utils.js', import.meta.url), 'utf8');
const { api, escapeHtml } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test('JSON defaults and caller headers are both retained', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/import');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers.get('content-type'), 'application/json');
    assert.equal(options.headers.get('x-reviewer'), 'alice');
    assert.equal(options.body, '{}');
    return Response.json({ saved: true });
  };
  assert.deepEqual(await api('/api/import', { method: 'POST', body: '{}', headers: { 'x-reviewer': 'alice' } }), { saved: true });
});

test('Headers instances and explicit content types are respected', async () => {
  globalThis.fetch = async (_, options) => {
    assert.equal(options.headers.get('content-type'), 'text/plain');
    assert.equal(options.headers.get('x-reviewer'), 'alice');
    return new Response(null, { status: 204 });
  };
  assert.equal(await api('/api/notes', { headers: new Headers({ 'content-type': 'text/plain', 'x-reviewer': 'alice' }) }), null);
});

test('validation errors identify the field', async () => {
  globalThis.fetch = async () => Response.json({ detail: [{ loc: ['body', 'candidates', 0, 'row'], msg: 'Expected an integer' }] }, { status: 422 });
  await assert.rejects(api('/api/import'), /candidates.0.row: Expected an integer/);
});

test('server error messages stay bounded', async () => {
  globalThis.fetch = async () => Response.json({ detail: 'x'.repeat(2000) }, { status: 500 });
  try { await api('/api/runs'); assert.fail('Expected an error'); }
  catch (error) { assert.ok(error.message.length < 450); }
});

test('source values are escaped in text and attribute contexts', () => {
  assert.equal(escapeHtml(`<b title="a&b">'x'</b>`), '&lt;b title=&quot;a&amp;b&quot;&gt;&#39;x&#39;&lt;/b&gt;');
});
