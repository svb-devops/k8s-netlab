/**
 * Regression test for the LabGen kubectl terminal's post-reconnect
 * output-loss bug:
 *
 *   Every time the terminal page is freshly loaded (a real page reload, or
 *   reopening after the kubectl WS idle-timed out — this app has no
 *   auto-reconnect, so "reconnect" always means a fresh page load), the
 *   drawer auto-opens on first activation (labgen-session-init.js). That
 *   drawer-open CSS transition narrows the terminal's container, and a
 *   delayed fit() (~260ms later, via _refitAfterDrawerTransition) reflows
 *   the xterm.js buffer to the new column count. If the WebSocket had
 *   already delivered the "ready" banner and/or the first command's
 *   echo/output by then, that delayed reflow silently lost/overwrote it —
 *   the learner saw the command flash by and then a blank terminal, even
 *   though the command executed correctly server-side (confirmed via
 *   server logs during the real production investigation on
 *   2026-07-18: session 165ae671..., exit=0, output never rendered).
 *
 *   Root cause: connect() opened the WebSocket (and could therefore start
 *   writing to the buffer) immediately, before the drawer-open transition
 *   (and its delayed refit) had settled. Fix: connect(settleDelayMs) defers
 *   WebSocket creation — and therefore all data — until after that delay,
 *   so there is nothing in the buffer for the delayed refit to corrupt.
 *
 * No jsdom in this project (see test_labgen_kubectl_terminal_paste.mjs's
 * docstring) — stub only the globals connect() actually touches.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));

class FakeTerminal {
    constructor(opts) { this.opts = opts; }
    loadAddon() {}
    open() {}
    onData(cb) { this._onData = cb; }
    scrollToBottom() {}
    write() {}
    writeln() {}
    dispose() {}
}

class FakeFitAddon {
    fit() {}
}

class FakeWebSocket {
    constructor(url) {
        this.url = url;
        this.readyState = FakeWebSocket.OPEN;
        FakeWebSocket.instances.push(this);
    }
    send() {}
    close() {}
}
FakeWebSocket.OPEN = 1;
FakeWebSocket.instances = [];

globalThis.Terminal = FakeTerminal;
globalThis.FitAddon = { FitAddon: FakeFitAddon };
globalThis.WebSocket = FakeWebSocket;
globalThis.document = {
    getElementById: () => ({ innerHTML: '' }),
};
globalThis.window = {
    location: { protocol: 'https:', host: 'test.local' },
    addEventListener() {},
    removeEventListener() {},
};

const { LabKubectlTerminal } =
    await import(resolve(__dir, '../../frontend/js/labgen-kubectl-terminal.js'));

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

test('connect() with no settle delay opens the WebSocket immediately (unchanged default behavior)', () => {
    FakeWebSocket.instances.length = 0;
    const t = new LabKubectlTerminal('sess-1', 'container-1');
    t.connect();
    assert.equal(FakeWebSocket.instances.length, 1, 'WebSocket must open synchronously when no delay is requested');
});

test('connect(settleDelayMs) does not open the WebSocket before the delay elapses', async () => {
    FakeWebSocket.instances.length = 0;
    const t = new LabKubectlTerminal('sess-2', 'container-1');
    t.connect(50);
    assert.equal(FakeWebSocket.instances.length, 0, 'no WebSocket — and therefore no data — may exist before the settle delay elapses');
    await sleep(80);
    assert.equal(FakeWebSocket.instances.length, 1, 'WebSocket must open once the settle delay has elapsed');
});

test('calling connect() again during the settle delay does not open a second WebSocket', async () => {
    FakeWebSocket.instances.length = 0;
    const t = new LabKubectlTerminal('sess-3', 'container-1');
    t.connect(50);
    t.connect(50); // e.g. a second snapshot poll re-entering _syncTerminal before settle
    t.connect(50);
    await sleep(80);
    assert.equal(FakeWebSocket.instances.length, 1, 'a settle delay in progress must not be re-triggered into a duplicate connection');
});

test('disconnect() during a pending settle delay cancels it — no socket opens on torn-down state', async () => {
    FakeWebSocket.instances.length = 0;
    const t = new LabKubectlTerminal('sess-4', 'container-1');
    t.connect(50);
    t.disconnect();
    await sleep(80);
    assert.equal(FakeWebSocket.instances.length, 0, 'a cancelled settle delay must never open a WebSocket');
    assert.equal(t._connecting, false, 'disconnect() must not leave the terminal stuck mid-connect');
});
