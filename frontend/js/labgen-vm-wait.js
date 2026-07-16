/**
 * P0 Reader Path Repair — polls GET /api/lab-sessions/vm-provisioning-status
 * until the background auto-provisioning job reaches a terminal state
 * ('ready' or 'failed'), or the timeout elapses.
 *
 * Single responsibility: polling only. Rendering/retry decisions stay in the
 * caller (labgen-lab-init.js).
 */
export async function waitForVmProvisioning(client, { intervalMs = 3000, timeoutMs = 300000 } = {}) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        const { status } = await client.getVmProvisioningStatus();
        if (status === 'ready' || status === 'failed') return status;
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    return 'timeout';
}
