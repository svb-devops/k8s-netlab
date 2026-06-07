/**
 * K8S NetLab - Terminal Manager
 *
 * Manages WebSocket connections and xterm.js terminal instances.
 */

class TerminalManager {
    constructor() {
        this.terminal = null;
        this.fitAddon = null;
        this.websocket = null;
        this.currentVMId = null;
        this.reconnectBtn = document.getElementById('btn-reconnect-terminal');
    }

    /**
     * Connect to VM terminal
     */
    async connect(vmId) {
        // Close existing connection
        this.disconnect();

        this.currentVMId = vmId;

        // Hide reconnect button while connecting
        if (this.reconnectBtn) this.reconnectBtn.classList.add('hidden');

        // Create xterm instance
        this.terminal = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
            theme: {
                background: '#1e1e1e',
                foreground: '#d4d4d4',
                cursor: '#ffffff',
                selection: '#264f78',
            },
            rows: 30,
            cols: 120,
        });

        // Add fit addon (auto resize)
        this.fitAddon = new FitAddon.FitAddon();
        this.terminal.loadAddon(this.fitAddon);

        // Add web links addon
        this.terminal.loadAddon(new WebLinksAddon.WebLinksAddon());

        // Show terminal section FIRST so the container has real dimensions.
        // xterm.js open() and fitAddon.fit() require a visible container;
        // calling them while the parent is display:none causes silent failure.
        document.getElementById('terminal-section').classList.remove('hidden');

        // Make drawer available now that terminal is active (was display:none before).
        const drawerEl   = document.getElementById('doc-drawer');
        const backdropEl = document.getElementById('doc-drawer-backdrop');
        if (drawerEl)   drawerEl.style.display   = 'flex';
        if (backdropEl) backdropEl.style.display  = 'block';

        // Mount to DOM
        const terminalContainer = document.getElementById('terminal');
        terminalContainer.innerHTML = ''; // Clear
        this.terminal.open(terminalContainer);
        this.fitAddon.fit();

        // Connect WebSocket
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/terminal/${vmId}`;

        this.websocket = new WebSocket(wsUrl);

        // WebSocket event handlers
        this.websocket.onopen = () => {
            console.log(`WebSocket connected to VM ${vmId}`);
            this.terminal.write('\r\n\x1b[32m✓ 正在连接到 VM ' + vmId + '...\x1b[0m\r\n');
        };

        this.websocket.onmessage = (event) => {
            try {
                // Only treat as control message if it's a JSON object with a type field
                const msg = JSON.parse(event.data);
                if (msg && typeof msg === 'object' && msg.type) {
                    if (msg.type === 'error') {
                        this.terminal.write('\r\n\x1b[31m✗ 错误: ' + msg.message + '\x1b[0m\r\n');
                    } else if (msg.type === 'waiting') {
                        this.terminal.write('\r\x1b[33m⏳ ' + msg.message + '\x1b[0m');
                    } else if (msg.type === 'connected') {
                        this.terminal.write('\r\n\x1b[32m✓ SSH 连接成功 (' + msg.vm_ip + ')\x1b[0m\r\n\r\n');
                    } else if (msg.type === 'disconnected') {
                        this.terminal.write('\r\n\x1b[33m✗ ' + msg.message + '\x1b[0m\r\n');
                        if (this.websocket) {
                            this.websocket.close();
                        }
                    } else {
                        // Unknown control message type, treat as terminal data
                        this.terminal.write(event.data);
                    }
                } else {
                    // Valid JSON but not a control object, treat as terminal data
                    this.terminal.write(event.data);
                }
            } catch {
                // Not JSON - normal terminal data
                this.terminal.write(event.data);
            }
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.terminal.write('\r\n\x1b[31m✗ WebSocket 连接错误\x1b[0m\r\n');
        };

        this.websocket.onclose = () => {
            console.log('WebSocket closed');
            this.terminal.write('\r\n\x1b[33m连接已关闭\x1b[0m  \x1b[2m(点击右上角"↻ 重新连接"恢复)\x1b[0m\r\n');
            // Show reconnect button
            if (this.reconnectBtn && this.currentVMId) {
                this.reconnectBtn.classList.remove('hidden');
                this.reconnectBtn.onclick = () => {
                    const vmId = this.currentVMId;
                    if (vmId) this.connect(vmId);
                };
            }
        };

        // Terminal input -> WebSocket
        this.terminal.onData((data) => {
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                this.websocket.send(data);
            }
        });

        // Window resize
        window.addEventListener('resize', () => {
            if (this.fitAddon) {
                this.fitAddon.fit();
            }
        });
    }

    /**
     * Disconnect terminal
     */
    disconnect() {
        if (this.reconnectBtn) this.reconnectBtn.classList.add('hidden');

        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }

        if (this.terminal) {
            this.terminal.dispose();
            this.terminal = null;
        }

        this.currentVMId = null;

        // Hide drawer and reset its state before hiding terminal section.
        const drawerEl   = document.getElementById('doc-drawer');
        const backdropEl = document.getElementById('doc-drawer-backdrop');
        if (drawerEl) {
            drawerEl.classList.remove('drawer-open');
            drawerEl.style.display = 'none';
        }
        if (backdropEl) {
            backdropEl.classList.remove('backdrop-visible');
            backdropEl.style.display = 'none';
        }

        // Hide terminal section
        document.getElementById('terminal-section').classList.add('hidden');
    }

    /**
     * Check if connected
     */
    isConnected() {
        return this.websocket && this.websocket.readyState === WebSocket.OPEN;
    }

    /**
     * Re-fit terminal to container size.
     * Called by drawer.js after drawer open/close transition ends.
     */
    fit() {
        if (this.fitAddon) {
            this.fitAddon.fit();
        }
    }
}

// Create global terminal manager instance
const terminalManager = new TerminalManager();
