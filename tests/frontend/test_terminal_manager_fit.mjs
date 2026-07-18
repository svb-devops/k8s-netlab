/**
 * Regression test for TerminalManager.fit() (frontend/js/terminal.js), part of
 * the 2026-07-18 fix that turned index.html's #doc-drawer from a fixed
 * overlay (covered part of the terminal, terminal itself never resized) into
 * a desktop push-layout sidebar (see app.css's #doc-drawer rules). Once the
 * drawer genuinely resizes the terminal, fitAddon.fit()'s reflow can leave
 * the cursor/current line above the visible viewport if the reflow needs
 * more rows at the new (narrower) column count — a known xterm.js +
 * fit-addon gotcha, already fixed the same way in
 * labgen-kubectl-terminal.js's fit(). Before this fix, terminal.js's fit()
 * never called scrollToBottom() at all (harmless while the drawer was a
 * pure overlay that never actually resized anything, but a real bug once
 * the resize became real).
 *
 * terminal.js is a plain (non-module) browser script — loaded via <script
 * src> — so it can't be imported directly in Node. Load it into an isolated
 * vm context with minimal DOM stubs, matching the established pattern in
 * test_article_terminal_highlight.mjs.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import vm from 'node:vm';

const __dir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dir, '../../frontend/js/terminal.js'), 'utf-8');

function _fakeElement() {
    return {
        classList: { add() {}, remove() {}, toggle() {} },
        addEventListener() {},
    };
}

function loadSandbox() {
    const sandbox = {
        document: {
            getElementById: () => _fakeElement(),
        },
        WebSocket: { OPEN: 1 },
        console,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    // terminal.js declares `class TerminalManager` at script top level — a
    // lexical (let-like) binding, not a property of the global object, so
    // `sandbox.TerminalManager` would be undefined without this explicit
    // attach. `this` at top-level sandboxed script scope is the global
    // object (sandbox).
    vm.runInContext(source + '\nthis.TerminalManager = TerminalManager;', sandbox, { filename: 'terminal.js' });
    return sandbox;
}

test('fit() calls fitAddon.fit()', () => {
    const sandbox = loadSandbox();
    const mgr = new sandbox.TerminalManager();
    const calls = [];
    mgr.fitAddon = { fit: () => calls.push('fit') };
    mgr.terminal = { scrollToBottom: () => calls.push('scrollToBottom') };
    mgr.fit();
    assert.ok(calls.includes('fit'), 'fit() must call fitAddon.fit()');
});

test('fit() calls terminal.scrollToBottom() after fitAddon.fit() — regression for the xterm.js reflow gotcha', () => {
    const sandbox = loadSandbox();
    const mgr = new sandbox.TerminalManager();
    const calls = [];
    mgr.fitAddon = { fit: () => calls.push('fit') };
    mgr.terminal = { scrollToBottom: () => calls.push('scrollToBottom') };
    mgr.fit();
    assert.deepEqual(calls, ['fit', 'scrollToBottom'], 'scrollToBottom() must run after fit(), not before');
});

test('fit() is a no-op (does not throw) when fitAddon is not yet set', () => {
    const sandbox = loadSandbox();
    const mgr = new sandbox.TerminalManager();
    assert.doesNotThrow(() => mgr.fit());
});

test('fit() does not throw if terminal is null but fitAddon exists', () => {
    const sandbox = loadSandbox();
    const mgr = new sandbox.TerminalManager();
    mgr.fitAddon = { fit: () => {} };
    mgr.terminal = null;
    assert.doesNotThrow(() => mgr.fit());
});
