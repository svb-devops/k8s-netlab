/**
 * Regression test for the LabGen kubectl terminal's paste-handling bug:
 *
 *   Pasting a command copied from the lab UI's suggested-command <code>
 *   block (or any source whose clipboard text ends in a bare LF, not CRLF)
 *   silently swallowed the trailing newline instead of treating it as
 *   Enter. _handleInput() only recognized code === 13 (CR) as "send the
 *   command" — a paste ending in "\n" (code 10) fell through to the
 *   "ignore other control characters" branch, so the command was echoed
 *   to the screen (looks typed) but never sent over the WebSocket. The
 *   learner sees the command flash onto the terminal with the cursor
 *   sitting at the end of the line and nothing happens — no output, no
 *   error — because the command was never actually submitted.
 *
 * No jsdom is set up in this project (frontend tests only exercise pure
 * functions — see test_client.mjs's docstring). LabKubectlTerminal's
 * constructor does not touch the DOM, and _handleInput only touches
 * this._ws (stubbed here) and this._write/_showPrompt, which are no-ops
 * when this._terminal is null (never set, since connect() is never
 * called) — so the class can be exercised directly without a real
 * browser/xterm.js/WebSocket.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));

// LabKubectlTerminal's _handleInput() reads the global WebSocket.OPEN
// constant to check readyState — Node has no global WebSocket, so stub the
// one field actually used before importing the module under test.
globalThis.WebSocket = { OPEN: 1 };

const { LabKubectlTerminal } =
    await import(resolve(__dir, '../../frontend/js/labgen-kubectl-terminal.js'));

function makeTerminal() {
    const t = new LabKubectlTerminal('sess-1', 'container-1');
    t._active = true;
    const sent = [];
    t._ws = {
        readyState: 1, // WebSocket.OPEN
        send: (msg) => sent.push(JSON.parse(msg)),
    };
    const writes = [];
    t._write = (text) => writes.push(text);
    return { t, sent, writes };
}

test('typed Enter (bare CR) sends the buffered command', () => {
    const { t, sent } = makeTerminal();
    t._handleInput('kubectl get pods');
    t._handleInput('\r');
    assert.equal(sent.length, 1);
    assert.equal(sent[0].cmd, 'kubectl get pods');
});

test('pasted text ending in a bare LF (no CR) still sends the command', () => {
    // Reproduces a paste from a <code> block whose clipboard text is
    // "kubectl get pods\n" (LF only, no CR) delivered as a single onData chunk.
    const { t, sent } = makeTerminal();
    t._handleInput('kubectl get pods\n');
    assert.equal(sent.length, 1, 'LF-terminated paste must be treated as Enter, not silently dropped');
    assert.equal(sent[0].cmd, 'kubectl get pods');
});

test('pasted text ending in CRLF sends the command exactly once', () => {
    const { t, sent } = makeTerminal();
    t._handleInput('kubectl get pods\r\n');
    assert.equal(sent.length, 1, 'CRLF paste must not send the command twice');
    assert.equal(sent[0].cmd, 'kubectl get pods');
});

test('pasted text ending in CRLF does not print a duplicate blank line/prompt', () => {
    // The LF half of a CRLF pair must be treated as part of the same line
    // ending, not as a second independent Enter — otherwise the terminal
    // prints an extra blank line and prompt right after sending.
    const { t, writes } = makeTerminal();
    t._handleInput('kubectl get pods\r\n');
    const newlineWrites = writes.filter((w) => w === '\r\n').length;
    assert.equal(newlineWrites, 1, 'CRLF must only trigger one "\\r\\n" write, not two');
});

test('a bare LF alone (empty buffer) does not send an empty command', () => {
    const { t, sent } = makeTerminal();
    t._handleInput('\n');
    assert.equal(sent.length, 0);
});
