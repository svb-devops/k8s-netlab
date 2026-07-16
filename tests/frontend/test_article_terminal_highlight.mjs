/**
 * Regression tests for article.js's terminal-chrome code block post-processing
 * (_enhanceCodeBlocks / _highlightDiagnosticText), added 2026-07-16 after owner
 * compared the real article page against an earlier Artifact mockup that had
 * hand-styled terminal windows and keyword highlighting.
 *
 * article.js is a plain (non-module) browser script that calls initAuth() at
 * load time, so it can't be imported directly in Node. This loads the file's
 * source into an isolated vm context with minimal DOM/fetch stubs (fetch
 * rejects immediately so initAuth's try/catch resolves without a real
 * network call) and exercises the pure escaping/highlighting functions
 * exposed on the sandbox global.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import vm from 'node:vm';

const __dir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dir, '../../frontend/js/article.js'), 'utf-8');

function _fakeElement() {
    return {
        innerHTML: '',
        textContent: '',
        classList: { add() {}, remove() {}, toggle() {} },
        addEventListener() {},
        appendChild() {},
        querySelectorAll: () => [],
        querySelector: () => null,
        closest: () => null,
    };
}

function loadSandbox() {
    const sandbox = {
        URLSearchParams,
        location: { search: '' },
        document: {
            getElementById: () => _fakeElement(),
            querySelector: () => null,
        },
        // initAuth's fetch is caught internally; loadArticle/loadLabCTA/loadRelatedArticles run
        // asynchronously afterward against the fake elements above and are
        // irrelevant to the synchronous function-level assertions below.
        fetch: () => Promise.reject(new Error('no network in test sandbox')),
        DOMPurify: { sanitize: (s) => s },
        marked: { parse: (s) => s },
        console,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox, { filename: 'article.js' });
    return sandbox;
}

test('escapeHtml: escapes & < > " but NOT single quote — document actual behavior', () => {
    // article.js's escapeHtml() only replaces four characters (&, <, >, ").
    // It's safe for the current usage (inserting escaped text into element
    // content, never into an HTML attribute value), but a future reuse of
    // this function inside an attribute-value context (e.g. `title='${x}'`)
    // would NOT be single-quote-safe. This test pins the real contract so
    // that assumption isn't silently wrong. If escapeHtml() is ever upgraded
    // to also escape `'`, update this assertion in the same change.
    const sandbox = loadSandbox();
    assert.equal(sandbox.escapeHtml(`<script>&"'`), '&lt;script&gt;&amp;&quot;\'');
});

test('_highlightDiagnosticText: wraps known diagnostic keywords in hl-bad spans', () => {
    const sandbox = loadSandbox();
    const out = sandbox._highlightDiagnosticText('STATUS   CrashLoopBackOff');
    assert.equal(out, 'STATUS   <span class="hl-bad">CrashLoopBackOff</span>');
});

test('_highlightDiagnosticText: highlights only the number after "Exit Code:"', () => {
    const sandbox = loadSandbox();
    const out = sandbox._highlightDiagnosticText('  Exit Code:    127');
    assert.equal(out, '  Exit Code:    <span class="hl-bad">127</span>');
});

test('_highlightDiagnosticText: escapes HTML in raw text BEFORE keyword wrapping — no XSS via CMS content', () => {
    const sandbox = loadSandbox();
    // A malicious/malformed article body should never result in an unescaped
    // tag reaching the DOM, even though this text also contains a real
    // diagnostic keyword that gets highlighted.
    const out = sandbox._highlightDiagnosticText('<img src=x onerror=alert(1)> not found');
    assert.ok(!out.includes('<img'), 'raw <img> tag must not survive into the output');
    assert.ok(out.includes('&lt;img'), 'the tag must be present only in escaped form');
    assert.ok(out.includes('<span class="hl-bad">not found</span>'), 'legitimate keyword highlighting still applies');
});

test('_highlightDiagnosticText: does not alter text with no diagnostic keywords', () => {
    const sandbox = loadSandbox();
    const out = sandbox._highlightDiagnosticText('kubectl get pods -n demo');
    assert.equal(out, 'kubectl get pods -n demo');
});
