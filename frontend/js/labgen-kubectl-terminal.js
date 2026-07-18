/**
 * LabGen Learner kubectl Terminal
 *
 * Manages the WebSocket connection and xterm.js instance for the
 * constrained kubectl terminal in a lab session page.
 *
 * The "use this terminal for the current lab only" security notice is a
 * static HTML banner in labgen-session.html, not printed into the terminal
 * buffer — terminal text wraps at the viewport's current column width, which
 * made a fixed two-line notice look ragged/misaligned at most sizes.
 *
 * Protocol (client → server):
 *   {"type": "command", "cmd": "<kubectl command>"}
 *
 * Protocol (server → client):
 *   {"type": "ready",   "namespace": "...", "msg": "..."}
 *   {"type": "output",  "text": "...", "exit_code": 0}
 *   {"type": "blocked", "text": "..."}
 *   {"type": "error",   "text": "..."}
 *   {"type": "closed",  "reason": "..."}
 */

export class LabKubectlTerminal {
    /**
     * @param {string} sessionId   - Lab session ID
     * @param {string} containerId - DOM element ID for the terminal
     */
    constructor(sessionId, containerId) {
        this._sessionId = sessionId;
        this._containerId = containerId;
        this._terminal = null;
        this._fitAddon = null;
        this._ws = null;
        this._inputBuffer = '';
        this._namespace = '';
        this._active = false;
        this._resizeHandler = null;
    }

    /** Connect to the lab kubectl WebSocket and mount xterm.js. */
    connect() {
        if (this._ws) return;

        const container = document.getElementById(this._containerId);
        if (!container) return;

        this._terminal = new Terminal({
            cursorBlink: true,
            fontSize: 13,
            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
            theme: {
                background: '#1a1a2e',
                foreground: '#e0e0e0',
                cursor: '#00d4aa',
                selection: '#264f78',
                green: '#00d4aa',
                yellow: '#ffd700',
                red: '#ff6b6b',
            },
            rows: 20,
            cols: 100,
            scrollback: 500,
        });

        this._fitAddon = new FitAddon.FitAddon();
        this._terminal.loadAddon(this._fitAddon);

        container.innerHTML = '';
        this._terminal.open(container);
        this.fit();

        this._resizeHandler = () => this.fit();
        window.addEventListener('resize', this._resizeHandler);

        // Connect WebSocket
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this._ws = new WebSocket(`${proto}//${window.location.host}/ws/lab-kubectl/${this._sessionId}`);

        this._ws.onopen = () => {
            this._active = true;
        };

        this._ws.onmessage = (ev) => this._handleMessage(ev);

        this._ws.onerror = () => {
            this._writeLine('\x1b[31mWebSocket connection error.\x1b[0m');
        };

        this._ws.onclose = () => {
            this._active = false;
            this._writeLine('\x1b[33m\r\n--- Terminal disconnected ---\x1b[0m');
        };

        // Handle keyboard input
        this._terminal.onData((data) => this._handleInput(data));
    }

    /** Disconnect and dispose of all resources. */
    disconnect() {
        this._active = false;

        if (this._resizeHandler) {
            window.removeEventListener('resize', this._resizeHandler);
            this._resizeHandler = null;
        }

        if (this._ws) {
            this._ws.close();
            this._ws = null;
        }

        if (this._terminal) {
            this._terminal.dispose();
            this._terminal = null;
            this._fitAddon = null;
        }

        this._inputBuffer = '';
    }

    /** Fit terminal to container. */
    fit() {
        if (!this._fitAddon) return;
        this._fitAddon.fit();
        // fitAddon.fit() reflows the buffer to the new column count but does not
        // re-scroll the viewport to follow the cursor. If the reflow increases the
        // number of buffer rows needed (e.g. a long in-progress command line wraps
        // onto more lines at a narrower width), the current line can end up above
        // the visible viewport — reads as the line having disappeared, even though
        // it's still in the buffer. This is a known xterm.js + fit-addon gotcha;
        // scrollToBottom() after fit() is the standard fix.
        if (this._terminal) this._terminal.scrollToBottom();
    }

    // ── Private ──────────────────────────────────────────────────────────

    _writeLine(text) {
        if (this._terminal) this._terminal.writeln(text);
    }

    _write(text) {
        if (this._terminal) this._terminal.write(text);
    }

    _handleMessage(ev) {
        let msg;
        try {
            msg = JSON.parse(ev.data);
        } catch {
            return;
        }

        switch (msg.type) {
            case 'ready': {
                this._namespace = msg.namespace || '';
                // xterm.js (convertEol defaults to false) treats a bare "\n" as
                // line-feed-only — it moves down a row without returning to column
                // 0. msg.msg arrives with plain "\n" line breaks (Python string),
                // so it must be normalized the same way output/blocked/error are
                // below, or each line after the first starts at whatever column
                // the previous line's cursor happened to end up at (staircase
                // indentation).
                const readyText = (msg.msg || 'Terminal ready.\n').replace(/\r?\n/g, '\r\n');
                this._write('\x1b[32m');
                this._write(readyText);
                this._write('\x1b[0m');
                this._showPrompt();
                break;
            }

            case 'output': {
                // Normalize \n to \r\n for xterm
                const text = (msg.text || '').replace(/\r?\n/g, '\r\n');
                this._write(text);
                if (!text.endsWith('\r\n')) this._write('\r\n');
                this._showPrompt();
                break;
            }

            case 'blocked':
                this._write('\x1b[33m⚠ ');
                this._write((msg.text || 'Blocked.').replace(/\r?\n/g, '\r\n'));
                this._write('\x1b[0m');
                if (!msg.text?.endsWith('\n')) this._write('\r\n');
                this._showPrompt();
                break;

            case 'error':
                this._write('\x1b[31m');
                this._write((msg.text || 'Error.').replace(/\r?\n/g, '\r\n'));
                this._write('\x1b[0m');
                if (!msg.text?.endsWith('\n')) this._write('\r\n');
                if (msg.text && !msg.text.includes('ended') && !msg.text.includes('disconnecting')) {
                    this._showPrompt();
                }
                break;

            case 'closed':
                this._write('\x1b[33m\r\n--- Session ended (');
                this._write(msg.reason || 'unknown');
                this._write(') ---\x1b[0m\r\n');
                break;
        }
    }

    _handleInput(data) {
        if (!this._active || !this._ws || this._ws.readyState !== WebSocket.OPEN) return;

        let prevWasCR = false;
        for (const ch of data) {
            const code = ch.charCodeAt(0);

            if (code === 10 && prevWasCR) {
                // The LF half of a CRLF pair — already handled by the
                // preceding CR below. Skip entirely so it isn't treated as a
                // second independent Enter (which would print an extra blank
                // line/prompt right after the command was sent).
                prevWasCR = false;
                continue;
            }
            prevWasCR = code === 13;

            if (code === 13 || code === 10) {
                // Enter — send command. Also treat a bare LF (10) as Enter:
                // pasted text (e.g. copied from a lab step's suggested-command
                // <code> block) commonly ends in a bare "\n", not "\r\n" — if
                // only CR were recognized, that trailing LF would silently
                // fall through to "ignore other control characters" below,
                // leaving the command echoed on screen but never sent.
                this._write('\r\n');
                const cmd = this._inputBuffer.trim();
                this._inputBuffer = '';
                if (cmd) {
                    this._ws.send(JSON.stringify({ type: 'command', cmd }));
                } else {
                    this._showPrompt();
                }
            } else if (code === 127 || code === 8) {
                // Backspace
                if (this._inputBuffer.length > 0) {
                    this._inputBuffer = this._inputBuffer.slice(0, -1);
                    this._write('\b \b');
                }
            } else if (code === 3) {
                // Ctrl-C — clear buffer and show new prompt
                this._inputBuffer = '';
                this._write('^C\r\n');
                this._showPrompt();
            } else if (code >= 32 && code < 127) {
                // Printable ASCII
                this._inputBuffer += ch;
                this._write(ch);
            }
            // Ignore other control characters (arrows, function keys, etc.)
        }
    }

    _showPrompt() {
        const ns = this._namespace ? `\x1b[36m[${this._namespace}]\x1b[0m ` : '';
        this._write(`${ns}\x1b[1m$\x1b[0m `);
    }
}
