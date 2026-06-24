/**
 * K8S NetLab - Main Application Logic
 *
 * Handles UI interactions, VM management, and real-time updates.
 */

class K8SNetLabApp {
    constructor() {
        this.vms = [];
        this.isLoading = false;
        this.refreshInterval = null;

        // DOM elements
        this.elements = {
            healthIndicator: document.getElementById('health-indicator'),
            statActiveVMs: document.getElementById('stat-active-vms'),
            statTotalVMs: document.getElementById('stat-total-vms'),
            statQuota: document.getElementById('stat-quota'),
            statSystemStatus: document.getElementById('stat-system-status'),
            vmList: document.getElementById('vm-list'),
            vmListEmpty: document.getElementById('vm-list-empty'),
            btnCreateVM: document.getElementById('btn-create-vm'),
            btnRefresh: document.getElementById('btn-refresh'),
            loadingModal: document.getElementById('loading-modal'),
            loadingText: document.getElementById('loading-text'),
            loadingSubtext: document.getElementById('loading-subtext'),
        };

        this.init();
    }

    /**
     * Initialize the application
     */
    async init() {
        console.log('K8S NetLab - Initializing...');

        // Redirect ?lab= deep-links to the LabGen lab page
        const labId = new URLSearchParams(window.location.search).get('lab');
        if (labId) {
            window.location.replace('/labgen-lab.html?labId=' + encodeURIComponent(labId));
            return;
        }

        // Check authentication
        await this.checkAuth();

        // Attach event listeners
        this.elements.btnCreateVM.addEventListener('click', () => this.handleCreateVM());
        this.elements.btnRefresh.addEventListener('click', () => this.refreshVMList());
        document.getElementById('btn-logout').addEventListener('click', () => this.handleLogout());
        document.getElementById('btn-disconnect-terminal').addEventListener('click', () => {
            terminalManager.disconnect();
            document.getElementById('terminal-vm-label').textContent = '';
        });

        // Initial health check and data load
        await this.checkHealth();
        await this.refreshVMList();

        // Start auto-refresh (every 10 seconds)
        this.startAutoRefresh(10000);

        console.log('K8S NetLab - Ready!');
    }

    /**
     * Check API health
     */
    async checkHealth() {
        const result = await api.healthCheck();

        if (result.status === 'healthy' && result.proxmox?.connected) {
            const version = result.proxmox.version ?? '';
            this.updateHealthIndicator(true, version ? `Proxmox v${version}` : 'Proxmox 已连接');
            this.elements.statSystemStatus.textContent = '正常';
        } else {
            this.updateHealthIndicator(false, '连接失败');
            this.elements.statSystemStatus.textContent = '异常';
        }
    }

    /**
     * Update health indicator
     */
    updateHealthIndicator(isHealthy, text) {
        const indicator = this.elements.healthIndicator;
        const dot = indicator.querySelector('.status-dot');
        const span = indicator.querySelector('#health-status-text');

        if (isHealthy) {
            dot.classList.remove('status-stopped');
            dot.classList.add('status-running');
            span.textContent = text;
            span.classList.remove('text-red-600');
            span.classList.add('text-green-600');
        } else {
            dot.classList.remove('status-running');
            dot.classList.add('status-stopped');
            span.textContent = text;
            span.classList.remove('text-green-600');
            span.classList.add('text-red-600');
        }
    }

    /**
     * Refresh VM list
     */
    async refreshVMList() {
        const result = await api.listVMs();

        if (result.success) {
            this.vms = result.data;
            this.renderVMList();
            this.updateStats();
        } else {
            console.error('Failed to load VMs:', result.error);
            this.showError('加载失败', result.error);
        }
    }

    /**
     * Render VM list table
     */
    renderVMList() {
        const vmListBody = this.elements.vmList;

        // Clear existing rows (except empty message)
        const existingRows = vmListBody.querySelectorAll('tr:not(#vm-list-empty)');
        existingRows.forEach(row => row.remove());

        // Show/hide empty message
        if (this.vms.length === 0) {
            this.elements.vmListEmpty.classList.remove('hidden');
            return;
        } else {
            this.elements.vmListEmpty.classList.add('hidden');
        }

        // Render VM rows (filter out template VMs)
        this.vms
            .filter(vm => !vm.template)  // Hide template VMs from list
            .forEach(vm => {
                const row = this.createVMRow(vm);
                vmListBody.insertBefore(row, this.elements.vmListEmpty);
            });
    }

    /**
     * Create a VM row element
     */
    createVMRow(vm) {
        const row = document.createElement('tr');
        row.className = 'hover:bg-gray-50 transition duration-150';

        const statusClass = vm.status === 'running' ? 'status-running' : 'status-stopped';
        const statusText = vm.status === 'running' ? '运行中' : '已停止';
        const statusColor = vm.status === 'running' ? 'text-green-600' : 'text-gray-600';

        const cpuText = vm.cpus ? `${vm.cpus} 核` : '-';
        const memText = vm.maxmem ? K8SNetLabAPI.formatMemory(vm.maxmem) : '-';
        const uptimeText = K8SNetLabAPI.formatUptime(vm.uptime || 0);

        row.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                ${escapeHtml(vm.vmid)}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                ${escapeHtml(vm.name)}
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center space-x-2">
                    <span class="status-dot ${statusClass}"></span>
                    <span class="text-sm ${statusColor} font-medium">${statusText}</span>
                </div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                CPU: ${cpuText} | RAM: ${memText}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                ${uptimeText}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                ${vm.status === 'running' ? `
                <button data-action="terminal" data-vmid="${vm.vmid}"
                        class="text-blue-600 hover:text-blue-900 transition duration-150">
                    终端
                </button>
                ` : ''}
                <button data-action="delete" data-vmid="${vm.vmid}"
                        class="text-red-600 hover:text-red-900 transition duration-150">
                    删除
                </button>
            </td>
        `;

        // Attach event listeners via addEventListener to comply with CSP (no inline handlers)
        const termBtn = row.querySelector('[data-action="terminal"]');
        if (termBtn) {
            termBtn.addEventListener('click', () => this.handleConnectTerminal(vm.vmid));
        }
        row.querySelector('[data-action="delete"]')
            .addEventListener('click', () => this.handleDeleteVM(vm.vmid));

        return row;
    }

    /**
     * Update statistics
     */
    updateStats() {
        const activeVMs = this.vms.filter(vm => vm.status === 'running').length;
        const totalVMs = this.vms.length;

        this.elements.statActiveVMs.textContent = activeVMs;
        this.elements.statTotalVMs.textContent = totalVMs;

        // Update quota display
        api.getQuota().then(result => {
            if (result.success && this.elements.statQuota) {
                const q = result.data.user;
                const sys = result.data.system;
                const sysFull = sys.available === 0;
                this.elements.statQuota.textContent = sysFull
                    ? `系统已满员 ${sys.current}/${sys.max} — 请等待同学释放环境`
                    : `我的配额: ${q.current}/${q.max} | 系统: ${sys.current}/${sys.max}`;
                // Warn when user or system quota is full
                const atLimit = q.available === 0 || sysFull;
                this.elements.statQuota.className =
                    atLimit
                        ? 'text-xs text-amber-500 mt-1 font-medium'
                        : 'text-xs text-gray-400 mt-1';
            }
        }).catch(() => {});
    }

    /**
     * Handle Create VM button click
     */
    async handleCreateVM() {
        if (this.isLoading) return;

        const confirmed = confirm('确定要创建新的实验环境吗？\n\n这将需要约 1-2 分钟时间。');
        if (!confirmed) return;

        // Show dynamic progress stages while waiting for VM creation
        const stages = [
            { delay: 0,    text: '正在克隆模板...', sub: '复制磁盘镜像，请稍候' },
            { delay: 20000, text: '正在配置 VM...', sub: '设置 CPU、内存、网络' },
            { delay: 50000, text: '正在启动系统...', sub: 'VM 启动中，即将完成' },
            { delay: 80000, text: '等待服务就绪...', sub: '系统初始化中' },
        ];
        const stageTimers = stages.map(s =>
            setTimeout(() => this.showLoading(s.text, s.sub), s.delay)
        );
        this.showLoading(stages[0].text, stages[0].sub);

        const result = await api.createVM();

        stageTimers.forEach(t => clearTimeout(t));
        this.hideLoading();

        if (result.success) {
            this.showSuccess(
                '创建成功！',
                `VM ${result.data.vm_id} (${result.data.name}) 已创建并启动。\n资源: ${result.data.cores} 核 CPU, ${result.data.memory_mb} MB 内存\n\n⏳ 网络就绪约需 1 分钟，终端连接时会自动等待。`
            );
            await this.refreshVMList();
        } else if (result.status === 503) {
            this.showCapacityFull(result.error);
        } else {
            this.showError('创建失败', result.error);
        }
    }

    /**
     * Handle Connect Terminal
     */
    async handleConnectTerminal(vmId) {
        if (this.isLoading) return;

        try {
            // Connect to VM terminal
            await terminalManager.connect(vmId);

            // Notify experiment docs manager so highwater marks are scoped to this VM
            if (window.experimentDocs) experimentDocs.setActiveVm(vmId);

            // Scroll to terminal section
            document.getElementById('terminal-section').scrollIntoView({
                behavior: 'smooth'
            });

        } catch (error) {
            console.error('Failed to connect terminal:', error);
            this.showError('连接失败', error.message);
        }
    }

    /**
     * Handle Delete VM
     */
    async handleDeleteVM(vmId) {
        if (this.isLoading) return;

        const confirmed = confirm(`确定要删除 VM ${vmId} 吗？\n\n此操作不可撤销。`);
        if (!confirmed) return;

        this.showLoading('删除环境中...', '正在停止并删除 VM');

        const result = await api.deleteVM(vmId);

        this.hideLoading();

        if (result.success) {
            this.showSuccess('删除成功', `VM ${vmId} 已删除`);
            // Close terminal if it's connected to the deleted VM
            if (terminalManager.currentVMId === vmId) {
                terminalManager.disconnect();
            }
            await this.refreshVMList();
        } else {
            this.showError('删除失败', result.error);
        }
    }

    /**
     * Show loading modal
     */
    showLoading(text, subtext) {
        this.isLoading = true;
        this.elements.loadingText.textContent = text;
        this.elements.loadingSubtext.textContent = subtext;
        this.elements.loadingModal.classList.remove('hidden');
        this.elements.loadingModal.classList.add('flex');
    }

    /**
     * Hide loading modal
     */
    hideLoading() {
        this.isLoading = false;
        this.elements.loadingModal.classList.add('hidden');
        this.elements.loadingModal.classList.remove('flex');
    }

    _showToast(title, message, colorClass, iconHtml, durationMs) {
        const id = `toast-${Date.now()}`;
        const toast = document.createElement('div');
        toast.id = id;
        toast.className = [
            'fixed top-6 left-1/2 -translate-x-1/2 z-50',
            `border rounded-xl shadow-xl ${colorClass}`,
            'p-5 max-w-md w-11/12 flex items-start space-x-3',
        ].join(' ');
        toast.innerHTML = `
            <div class="text-2xl select-none">${iconHtml}</div>
            <div class="flex-1 min-w-0">
                <p class="font-semibold">${title}</p>
                ${message ? `<p class="text-sm mt-1 break-words whitespace-pre-wrap">${message}</p>` : ''}
            </div>
            <button class="text-xl leading-none flex-shrink-0 opacity-60 hover:opacity-100">✕</button>
        `;
        document.body.appendChild(toast);
        toast.querySelector('button').addEventListener('click', () => toast.remove());
        setTimeout(() => { if (toast.isConnected) toast.remove(); }, durationMs);
    }

    showSuccess(title, message) {
        this._showToast(
            title, message,
            'bg-green-50 border-green-300 text-green-800',
            '✅', 6000
        );
    }

    showError(title, message) {
        this._showToast(
            title, message,
            'bg-red-50 border-red-300 text-red-800',
            '❌', 8000
        );
    }

    /**
     * Show capacity-full notice (friendly banner, not alert)
     */
    showCapacityFull(message) {
        const existing = document.getElementById('capacity-notice');
        if (existing) existing.remove();

        const notice = document.createElement('div');
        notice.id = 'capacity-notice';
        notice.className = [
            'fixed top-6 left-1/2 -translate-x-1/2 z-50',
            'bg-amber-50 border border-amber-300 rounded-xl shadow-xl',
            'p-5 max-w-md w-11/12 flex items-start space-x-3',
        ].join(' ');
        notice.innerHTML = `
            <div class="text-2xl select-none">⏳</div>
            <div class="flex-1 min-w-0">
                <p class="font-semibold text-amber-800">实验环境已满员</p>
                <p class="text-sm text-amber-700 mt-1 break-words">${message}</p>
                <p class="text-xs text-amber-500 mt-2">本平台运行在家庭实验室（车库服务器），硬件资源有限，最多支持 15 人同时使用。配额状态每 30 秒自动刷新，空位出现后可立即重试。</p>
            </div>
            <button id="capacity-notice-close"
                    class="text-amber-400 hover:text-amber-600 text-xl leading-none flex-shrink-0">✕</button>
        `;
        document.body.appendChild(notice);

        document.getElementById('capacity-notice-close')
            .addEventListener('click', () => notice.remove());

        // Auto-dismiss after 60s
        setTimeout(() => { if (notice.isConnected) notice.remove(); }, 60000);
    }

    /**
     * Start auto-refresh
     */
    startAutoRefresh(intervalMs) {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }

        this.refreshInterval = setInterval(() => {
            if (!this.isLoading) {
                this.refreshVMList();
                this.checkHealth();
            }
        }, intervalMs);

        console.log(`Auto-refresh started (${intervalMs}ms interval)`);
    }

    /**
     * Stop auto-refresh
     */
    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
            console.log('Auto-refresh stopped');
        }
    }

    /**
     * Check authentication
     */
    async checkAuth() {
        try {
            const response = await fetch('/api/auth/me', {
                credentials: 'include'
            });

            // Only redirect to login on explicit auth failure (401/403)
            if (response.status === 401 || response.status === 403) {
                console.log('Not authenticated, redirecting to login...');
                window.location.href = '/login.html';
                return;
            }

            if (!response.ok) {
                // Server error — don't redirect, user may still be authenticated
                console.warn('Auth check returned server error:', response.status);
                return;
            }

            const result = await response.json();

            // Update username display
            if (result.username) {
                document.getElementById('username-display').textContent = result.username;
            }

        } catch (error) {
            // Network error — don't redirect, backend may be temporarily unavailable
            console.error('Auth check failed (network):', error);
        }
    }

    /**
     * Handle logout
     */
    async handleLogout() {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                credentials: 'same-origin'  // Include cookies
            });
            window.location.href = '/login.html';
        } catch (error) {
            console.error('Logout failed:', error);
            window.location.href = '/login.html';
        }
    }
}

/**
 * Escape HTML special characters to prevent XSS in innerHTML contexts.
 * @param {string|number} value
 * @returns {string}
 */
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Initialize app when DOM is ready
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new K8SNetLabApp();
});
