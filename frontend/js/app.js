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
            const version = result.proxmox.version ?? '已连接';
            this.updateHealthIndicator(true, `Proxmox v${version}`);
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
        const span = indicator.querySelector('span');

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
                ${vm.vmid}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                ${vm.name}
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
                <button onclick="app.handleConnectTerminal(${vm.vmid})"
                        class="text-blue-600 hover:text-blue-900 transition duration-150">
                    终端
                </button>
                ` : ''}
                <button onclick="app.handleDeleteVM(${vm.vmid})"
                        class="text-red-600 hover:text-red-900 transition duration-150">
                    删除
                </button>
            </td>
        `;

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
    }

    /**
     * Handle Create VM button click
     */
    async handleCreateVM() {
        if (this.isLoading) return;

        const confirmed = confirm('确定要创建新的实验环境吗？\n\n这将需要约 1-2 分钟时间。');
        if (!confirmed) return;

        this.showLoading('创建环境中...', '正在克隆模板并配置资源，预计需要 1-2 分钟');

        const result = await api.createVM();

        this.hideLoading();

        if (result.success) {
            this.showSuccess(
                '创建成功！',
                `VM ${result.data.vm_id} (${result.data.name}) 已创建并启动。\n资源: ${result.data.cores} 核 CPU, ${result.data.memory_mb} MB 内存\n\n⏳ 网络就绪约需 1 分钟，终端连接时会自动等待。`
            );
            await this.refreshVMList();
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

    /**
     * Show success message
     */
    showSuccess(title, message) {
        alert(`✅ ${title}\n\n${message}`);
    }

    /**
     * Show error message
     */
    showError(title, message) {
        alert(`❌ ${title}\n\n${message}`);
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

// Initialize app when DOM is ready
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new K8SNetLabApp();
});
