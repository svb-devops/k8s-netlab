import { LabGenClient, LabGenApiError } from '/js/labgenClient.js';
import { renderLabDetail, renderErrorState, renderNotFound, renderLoading } from '/js/labgenViews.js';
import { waitForVmProvisioning } from '/js/labgen-vm-wait.js';

const root = document.getElementById('root');
const devInfo = document.getElementById('dev-user-info');

async function init() {
    root.innerHTML = renderLoading('dark');

    const client = new LabGenClient();
    const me = await client.getMe();
    if (!me) {
        window.location.href = '/login.html?next=' + encodeURIComponent(window.location.href);
        return;
    }
    devInfo.textContent = me.username;

    const labId = new URLSearchParams(window.location.search).get('labId');
    if (!labId) {
        root.innerHTML = renderErrorState('Missing ?labId= parameter.', 'dark');
        return;
    }

    try {
        const [lab, eligibility] = await Promise.all([
            client.getLabDetail(labId),
            client.getStartEligibility(labId),
        ]);
        document.getElementById('page-title').textContent = lab?.title ?? 'Lab Detail';
        root.innerHTML = renderLabDetail({ lab, eligibility });
        attachStartAction(client, labId);
    } catch (e) {
        if (e instanceof LabGenApiError && e.status === 404) {
            root.innerHTML = renderNotFound('Lab', 'dark');
        } else {
            root.innerHTML = renderErrorState(
                e instanceof LabGenApiError ? e.message : 'Failed to load lab.', 'dark'
            );
        }
    }
}

function _showGenericRetryMessage(btn) {
    // Deliberately generic — never surface VMID/Proxmox/internal error detail here.
    const errDiv = document.createElement('p');
    errDiv.className = 'text-red-400 text-sm mt-2 font-plex';
    errDiv.textContent = '实验环境准备遇到问题，请稍后重试';
    btn.insertAdjacentElement('afterend', errDiv);
}

async function _startAfterAutoProvisioning(client, labId, btn) {
    btn.textContent = '正在准备实验环境…';
    let outcome;
    try {
        outcome = await waitForVmProvisioning(client);
    } catch (pollErr) {
        // Polling itself failed (network error / 5xx from the status endpoint) —
        // must still restore the button, otherwise the learner is stuck on a
        // disabled "正在准备实验环境…" state with no way to retry short of reload.
        _showGenericRetryMessage(btn);
        btn.disabled = false;
        btn.textContent = 'Start Lab';
        return;
    }
    if (outcome !== 'ready') {
        _showGenericRetryMessage(btn);
        btn.disabled = false;
        btn.textContent = 'Start Lab';
        return;
    }
    try {
        const session = await client.startLab(labId);
        window.location.href = `/labgen-session.html?sessionId=${encodeURIComponent(session?.session_id ?? session?.id ?? '')}`;
    } catch (retryErr) {
        _showGenericRetryMessage(btn);
        btn.disabled = false;
        btn.textContent = 'Start Lab';
    }
}

function attachStartAction(client, labId) {
    const btn = root.querySelector('[data-action="start-lab"]');
    if (!btn || btn.disabled) return;
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Starting…';
        try {
            const session = await client.startLab(labId);
            window.location.href = `/labgen-session.html?sessionId=${encodeURIComponent(session?.session_id ?? session?.id ?? '')}`;
        } catch (e) {
            if (e instanceof LabGenApiError && (e.code === 'vm_provisioning' || e.code === 'vm_provisioning_failed')) {
                // P0 Reader Path Repair: auto-provisioning in progress (or just failed) —
                // never send the user to /app, poll until ready and retry automatically.
                if (e.code === 'vm_provisioning_failed') {
                    _showGenericRetryMessage(btn);
                    btn.disabled = false;
                    btn.textContent = 'Start Lab';
                    return;
                }
                await _startAfterAutoProvisioning(client, labId, btn);
                return;
            }
            btn.disabled = false;
            btn.textContent = 'Start Lab';
            if (e instanceof LabGenApiError && e.code === 'no_vm_assigned') {
                const returnUrl = '/app?next=' + encodeURIComponent(window.location.href);
                const block = document.createElement('div');
                block.className = 'mt-3 p-3 bg-amber-500/10 border border-amber-500/30 rounded text-sm font-plex';
                block.innerHTML =
                    '<p class="text-amber-400 mb-2">需要先创建 Kubernetes 实验环境，才能开始此实验。</p>' +
                    '<a href="' + returnUrl + '" ' +
                    'class="inline-block bg-k8s-blue hover:bg-blue-500 text-white px-3 py-1.5 rounded text-sm">' +
                    '前往创建实验环境 →</a>' +
                    '<p class="text-amber-400/80 mt-2 text-xs">创建完成后将自动返回此实验。</p>';
                btn.insertAdjacentElement('afterend', block);
            } else {
                const msg = e instanceof LabGenApiError ? e.message : 'Failed to start lab.';
                const errDiv = document.createElement('p');
                errDiv.className = 'text-red-400 text-sm mt-2 font-plex';
                errDiv.textContent = msg;
                btn.insertAdjacentElement('afterend', errDiv);
            }
        }
    });
}

init();
