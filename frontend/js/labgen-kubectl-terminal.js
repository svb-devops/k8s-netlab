/**
 * LabGen Learner kubectl Terminal
 *
 * Manages the WebSocket connection and xterm.js instance for the
 * constrained kubectl terminal in a lab session page.
 *
 * Security notice displayed in terminal:
 *   "Use this terminal for the current lab only.
 *    Do not enter real passwords, tokens, API keys, or private keys."
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
        this._fitAddon.fit();

        this._resizeHandler = () => {
            if (this._fitAddon) this._fitAddon.fit();
        };
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
        if (this._fitAddon) this._fitAddon.fit();
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
            case 'ready':
                this._namespace = msg.namespace || '';
                this._write('\x1b[32m');
                this._write(msg.msg || 'Terminal ready.\r\n');
                this._write('\x1b[0m');
                this._showSecurityNotice();
                this._showPrompt();
                break;

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

        for (const ch of data) {
            const code = ch.charCodeAt(0);

            if (code === 13) {
                // Enter — send command
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

    _showSecurityNotice() {
        this._writeLine('\x1b[2m⚠  Use this terminal for the current lab only.');
        this._writeLine('   Do not enter real passwords, tokens, API keys, or private keys.\x1b[0m');
    }
}
