/**
 * Tests for frontend/js/labgenSecurity.js
 * Run with: node --test tests/frontend/test_security.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));
const { sanitizeDisplayText, escapeHtml, assertNoSensitiveDisplayData } =
    await import(resolve(__dir, '../../frontend/js/labgenSecurity.js'));

// ── sanitizeDisplayText ────────────────────────────────────────────────────────

test('sanitizeDisplayText: passthrough for normal text', () => {
    assert.equal(sanitizeDisplayText('Hello world'), 'Hello world');
});

test('sanitizeDisplayText: returns non-string unchanged', () => {
    assert.equal(sanitizeDisplayText(42), 42);
    assert.equal(sanitizeDisplayText(null), null);
});

test('sanitizeDisplayText: redacts JWT token', () => {
    const jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    const result = sanitizeDisplayText(jwt);
    assert.ok(!result.includes('eyJ'), `JWT not redacted: ${result}`);
    assert.ok(result.includes('[REDACTED]'), `Expected [REDACTED], got: ${result}`);
});

test('sanitizeDisplayText: redacts long base64 blob', () => {
    const blob = 'A'.repeat(65);
    const result = sanitizeDisplayText(blob);
    assert.ok(!result.includes(blob), `Base64 not redacted`);
    assert.ok(result.includes('[REDACTED]'));
});

test('sanitizeDisplayText: preserves short base64-like strings (e.g. step IDs)', () => {
    const short = 'c3RlcC0x'; // 8 chars — step ID style
    assert.equal(sanitizeDisplayText(short), short);
});

test('sanitizeDisplayText: redacts Bearer token', () => {
    const result = sanitizeDisplayText('Authorization: Bearer eyJtoken123456789');
    assert.ok(!result.includes('eyJtoken123456789'), 'Bearer token not redacted');
});

test('sanitizeDisplayText: handles empty string', () => {
    assert.equal(sanitizeDisplayText(''), '');
});

// ── escapeHtml ────────────────────────────────────────────────────────────────

test('escapeHtml: escapes angle brackets', () => {
    assert.equal(escapeHtml('<script>'), '&lt;script&gt;');
});

test('escapeHtml: escapes ampersand', () => {
    assert.equal(escapeHtml('a & b'), 'a &amp; b');
});

test('escapeHtml: escapes quotes', () => {
    assert.equal(escapeHtml('"hello"'), '&quot;hello&quot;');
});

test('escapeHtml: converts non-string to string', () => {
    assert.equal(escapeHtml(42), '42');
    assert.equal(escapeHtml(null), '');
});

// ── assertNoSensitiveDisplayData ──────────────────────────────────────────────

test('assertNoSensitiveDisplayData: passes for clean html', () => {
    // Should not throw
    assertNoSensitiveDisplayData('<p>Create a pod with 2 replicas</p>');
});

test('assertNoSensitiveDisplayData: throws on injected sensitive value', () => {
    const html = '<p>Token: supersecretvalue</p>';
    assert.throws(
        () => assertNoSensitiveDisplayData(html, ['supersecretvalue']),
        /Sensitive injected value leaked/
    );
});

test('assertNoSensitiveDisplayData: throws on JWT in rendered html', () => {
    const jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    assert.throws(
        () => assertNoSensitiveDisplayData(`<p>${jwt}</p>`),
        /JWT token pattern/
    );
});

test('assertNoSensitiveDisplayData: throws on long base64 in rendered html', () => {
    const blob = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'; // 64 chars
    assert.throws(
        () => assertNoSensitiveDisplayData(`<p>${blob}</p>`),
        /Long base64 blob/
    );
});

test('assertNoSensitiveDisplayData: throws on absolute keyword kubeconfig', () => {
    assert.throws(
        () => assertNoSensitiveDisplayData('<pre>kubeconfig content here</pre>'),
        /kubeconfig/
    );
});

test('assertNoSensitiveDisplayData: throws on traceback', () => {
    assert.throws(
        () => assertNoSensitiveDisplayData('<pre>Traceback (most recent call last):\n  File...</pre>'),
        /Traceback/
    );
});

test('assertNoSensitiveDisplayData: throws on raw_model_output', () => {
    assert.throws(
        () => assertNoSensitiveDisplayData('<p>raw_model_output: {"choices":[...]}</p>'),
        /raw_model_output/
    );
});

test('assertNoSensitiveDisplayData: multiple injected values, first match throws', () => {
    assert.throws(
        () => assertNoSensitiveDisplayData('<p>bad_value_1</p>', ['bad_value_1', 'bad_value_2']),
        /Sensitive injected value leaked/
    );
});

test('assertNoSensitiveDisplayData: throws on non-string input', () => {
    assert.throws(
        () => assertNoSensitiveDisplayData({ html: 'oops' }),
        /TypeError/
    );
});
