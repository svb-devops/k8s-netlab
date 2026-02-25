/**
 * K8S NetLab - API Client
 *
 * Provides a clean interface for communicating with the backend API.
 * All API calls return Promise<{success: boolean, data: any, error: string}>.
 */

class K8SNetLabAPI {
    constructor(baseURL = '') {
        this.baseURL = baseURL;
        this.apiPrefix = '/api';
    }

    /**
     * Generic fetch wrapper with error handling
     */
    async _fetch(endpoint, options = {}) {
        const url = `${this.baseURL}${this.apiPrefix}${endpoint}`;

        try {
            const response = await fetch(url, {
                ...options,
                credentials: 'same-origin',  // Include cookies for authentication
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers,
                },
            });

            // Parse JSON response
            const data = await response.json();

            // Handle HTTP errors
            if (!response.ok) {
                throw new Error(data.detail || data.error || `HTTP ${response.status}`);
            }

            return data;

        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            return {
                success: false,
                data: null,
                error: error.message || 'Network error'
            };
        }
    }

    /**
     * Health Check
     * GET /api/health
     */
    async healthCheck() {
        return await this._fetch('/health');
    }

    /**
     * List all VMs
     * GET /api/vms
     */
    async listVMs() {
        return await this._fetch('/vms');
    }

    /**
     * Get VM status
     * GET /api/vms/{vm_id}/status
     */
    async getVMStatus(vmId) {
        return await this._fetch(`/vms/${vmId}/status`);
    }

    /**
     * Create a new VM
     * POST /api/vms/create
     *
     * @param {number|null} vmId - VM ID (optional, will auto-assign if null)
     * @param {number} templateId - Template VM ID (default: 100)
     */
    async createVM(vmId = null, templateId = 100) {
        const body = { template_id: templateId };
        if (vmId !== null) {
            body.vm_id = vmId;
        }

        return await this._fetch('/vms/create', {
            method: 'POST',
            body: JSON.stringify(body),
        });
    }

    /**
     * Delete a VM
     * DELETE /api/vms/{vm_id}?force=true
     */
    async deleteVM(vmId, force = true) {
        return await this._fetch(`/vms/${vmId}?force=${force}`, {
            method: 'DELETE',
        });
    }

    async getQuota() {
        return await this._fetch('/quota');
    }

    /**
     * Utility: Format uptime in seconds to human-readable string
     */
    static formatUptime(seconds) {
        if (seconds === 0) return '已停止';

        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;

        if (hours > 0) {
            return `${hours}小时 ${minutes}分钟`;
        } else if (minutes > 0) {
            return `${minutes}分钟 ${secs}秒`;
        } else {
            return `${secs}秒`;
        }
    }

    /**
     * Utility: Format memory in bytes to human-readable string
     */
    static formatMemory(bytes) {
        if (bytes === 0) return '0 MB';

        const mb = Math.floor(bytes / (1024 * 1024));
        const gb = Math.floor(bytes / (1024 * 1024 * 1024));

        if (gb > 0) {
            return `${gb} GB`;
        } else {
            return `${mb} MB`;
        }
    }

    /**
     * Utility: Format CPU usage percentage
     */
    static formatCPU(cpuUsage) {
        return `${(cpuUsage * 100).toFixed(1)}%`;
    }
}

// Create global API instance
const api = new K8SNetLabAPI();
