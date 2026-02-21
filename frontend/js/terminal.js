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
    }

    /**
     * Connect to VM terminal
     */
    async connect(vmId) {
        // Close existing connection
        this.disconnect();

        this.currentVMId = vmId;

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

        // Mount to DOM
        const terminalContainer = document.getElementById('terminal');
        terminalContainer.innerHTML = ''; // Clear
        this.terminal.open(terminalContainer);
        this.fitAddon.fit();

        // Show terminal section
        document.getElementById('terminal-section').classList.remove('hidden');

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
                // Try parse JSON message
                const msg = JSON.parse(event.data);
                if (msg.type === 'error') {
                    this.terminal.write('\r\n\x1b[31m✗ 错误: ' + msg.message + '\x1b[0m\r\n');
                } else if (msg.type === 'connected') {
                    this.terminal.write('\r\n\x1b[32m✓ SSH 连接成功 (' + msg.vm_ip + ')\x1b[0m\r\n\r\n');
                } else if (msg.type === 'disconnected') {
                    this.terminal.write('\r\n\x1b[33m✗ ' + msg.message + '\x1b[0m\r\n');
                    // Close WebSocket connection
                    if (this.websocket) {
                        this.websocket.close();
                    }
                }
            } catch {
                // Normal terminal data
                this.terminal.write(event.data);
            }
        };

        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.terminal.write('\r\n\x1b[31m✗ WebSocket 连接错误\x1b[0m\r\n');
        };

        this.websocket.onclose = () => {
            console.log('WebSocket closed');
            this.terminal.write('\r\n\x1b[33m✗ 连接已关闭\x1b[0m\r\n');
        };

        // Terminal input -> WebSocket
        this.terminal.onData((data) => {
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                // Local echo for digit keys (48-57) to fix SSH echo issue
                const charCode = data.charCodeAt(0);
                if (charCode >= 48 && charCode <= 57 && data.length === 1) {
                    // Digit key - echo locally
                    this.terminal.write(data);
                }

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
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }

        if (this.terminal) {
            this.terminal.dispose();
            this.terminal = null;
        }

        this.currentVMId = null;

        // Hide terminal section
        document.getElementById('terminal-section').classList.add('hidden');
    }

    /**
     * Check if connected
     */
    isConnected() {
        return this.websocket && this.websocket.readyState === WebSocket.OPEN;
    }
}

// Create global terminal manager instance
const terminalManager = new TerminalManager();
