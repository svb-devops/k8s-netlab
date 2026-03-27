// ── Experiment title map (matches docs_routes.py) ──────────────────────────
const EXP_TITLES = {
    '01': 'Kubernetes 网络基础',
    '02': 'Pod 网络深入探索',
    '03': 'Service 负载均衡',
    '04': 'Ingress 控制器详解',
    '05': 'NetworkPolicy 网络策略',
    '06': 'DNS 服务发现',
    '07': '持久化存储 PV/PVC',
    '08': 'ConfigMap 和 Secret',
    '09': 'StatefulSet 有状态应用',
    '10': '监控和日志管理',
    '11': '综合实战项目',
};

// ── State ──────────────────────────────────────────────────────────────────
let adminToken = sessionStorage.getItem('admin_token') || '';
let autoRefreshTimer = null;

// ── DOM refs ───────────────────────────────────────────────────────────────
const tokenGate    = document.getElementById('token-gate');
const dashboard    = document.getElementById('dashboard');
const tokenForm    = document.getElementById('token-form');
const tokenInput   = document.getElementById('token-input');
const tokenError   = document.getElementById('token-error');
const btnRefresh   = document.getElementById('btn-refresh');
const btnLogout    = document.getElementById('btn-logout');
const autoToggle   = document.getElementById('auto-refresh-toggle');
const autoLabel    = document.getElementById('auto-refresh-indicator');
const lastUpdated  = document.getElementById('last-updated');
const noSessions   = document.getElementById('no-sessions');
const sessionsTable= document.getElementById('sessions-table');
const tbody        = document.getElementById('sessions-tbody');

// ── Helpers ────────────────────────────────────────────────────────────────
function timeAgo(isoStr) {
    if (!isoStr) return '—';
    const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
    if (diff < 60)  return `${diff}秒前`;
    if (diff < 3600) return `${Math.floor(diff/60)}分钟前`;
    if (diff < 86400) return `${Math.floor(diff/3600)}小时前`;
    return `${Math.floor(diff/86400)}天前`;
}

function formatDate(isoStr) {
    if (!isoStr) return '—';
    return new Date(isoStr).toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
    });
}

function remainingTime(isoStr) {
    if (!isoStr) return '—';
    const mins = Math.floor((new Date(isoStr) - Date.now()) / 60000);
    if (mins <= 0) return '<span class="text-red-500">已过期</span>';
    if (mins < 60) return `<span class="text-yellow-600">${mins}分钟</span>`;
    return `${Math.floor(mins/60)}小时`;
}

function vmAgeColor(age) {
    if (age < 15) return 'bg-green-100 text-green-700';
    if (age < 25) return 'bg-yellow-100 text-yellow-700';
    return 'bg-red-100 text-red-700';
}

// ── Fetch & Render ─────────────────────────────────────────────────────────
async function fetchStatus() {
    const resp = await fetch('/api/admin/status', {
        headers: { 'X-Admin-Token': adminToken }
    });
    if (resp.status === 403 || resp.status === 503) {
        const data = await resp.json();
        throw new Error(data.detail || `HTTP ${resp.status}`);
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

function renderStats(stats) {
    document.getElementById('stat-total-users').textContent     = stats.total_users;
    document.getElementById('stat-active-sessions').textContent = stats.active_sessions;
    document.getElementById('stat-total-vms').textContent       = stats.total_tracked_vms;
}

function renderSessions(sessions) {
    if (!sessions.length) {
        noSessions.classList.remove('hidden');
        sessionsTable.classList.add('hidden');
        return;
    }
    noSessions.classList.add('hidden');
    sessionsTable.classList.remove('hidden');

    tbody.innerHTML = sessions.map(s => {
        const adminBadge = s.is_admin
            ? `<span class="ml-1.5 text-xs font-semibold px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded border border-amber-300">管理员</span>`
            : '';

        const expLabel = s.current_experiment
            ? `<span class="font-mono text-xs bg-blue-50 text-k8s-blue px-2 py-0.5 rounded">
                 实验${s.current_experiment}
               </span>
               <span class="text-gray-500 text-xs ml-1">${EXP_TITLES[s.current_experiment] || ''}</span>`
            : '<span class="text-gray-300">—</span>';

        const vmsHtml = s.vms.length
            ? s.vms.map(v =>
                `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono ${vmAgeColor(v.age_minutes)}">
                    VM-${v.vm_id} <span class="opacity-70">${Math.round(v.age_minutes)}m</span>
                 </span>`
              ).join(' ')
            : '<span class="text-gray-300">—</span>';

        const ipDisplay = s.login_ip
            ? `<span class="font-mono">${s.login_ip}</span>
               ${s.login_location ? `<span class="text-gray-400 block">${s.login_location}</span>` : ''}`
            : '<span class="text-gray-300">—</span>';

        return `<tr class="hover:bg-gray-50 transition">
            <td class="px-6 py-4 font-medium text-gray-900">${s.username}${adminBadge}</td>
            <td class="px-6 py-4 text-xs">${ipDisplay}</td>
            <td class="px-6 py-4 text-gray-500 text-xs">${formatDate(s.registered_at)}</td>
            <td class="px-6 py-4 text-gray-500 text-xs">${formatDate(s.login_time)}</td>
            <td class="px-6 py-4">${expLabel}</td>
            <td class="px-6 py-4 text-gray-500 text-xs">${timeAgo(s.last_activity)}</td>
            <td class="px-6 py-4">${vmsHtml}</td>
            <td class="px-6 py-4 text-xs">${remainingTime(s.expires_at)}</td>
            <td class="px-6 py-4">
                <button class="text-xs text-red-500 hover:text-red-700 hover:underline"
                        onclick="openResetModal('${s.username}')">重置密码</button>
            </td>
        </tr>`;
    }).join('');

}

async function refresh() {
    btnRefresh.disabled = true;
    btnRefresh.textContent = '加载中…';
    try {
        const data = await fetchStatus();
        renderStats(data.stats);
        renderSessions(data.sessions);
        lastUpdated.textContent = `更新于 ${new Date().toLocaleTimeString('zh-CN')}`;
    } catch (err) {
        if (err.message.includes('403') || err.message.includes('Invalid')) {
            logout();
            return;
        }
        lastUpdated.textContent = `错误: ${err.message}`;
    } finally {
        btnRefresh.disabled = false;
        btnRefresh.textContent = '刷新';
    }
}

// ── Auth ───────────────────────────────────────────────────────────────────
async function login(token) {
    // Probe the endpoint to verify token before entering dashboard
    try {
        const resp = await fetch('/api/admin/status', {
            headers: { 'X-Admin-Token': token }
        });
        if (resp.status === 403) {
            tokenError.textContent = 'Token 无效，请重试';
            tokenError.classList.remove('hidden');
            return;
        }
        if (resp.status === 503) {
            tokenError.textContent = '服务端未配置 ADMIN_TOKEN';
            tokenError.classList.remove('hidden');
            return;
        }
        if (!resp.ok) {
            tokenError.textContent = `服务器错误 (HTTP ${resp.status})`;
            tokenError.classList.remove('hidden');
            return;
        }
        const data = await resp.json();
        adminToken = token;
        sessionStorage.setItem('admin_token', token);
        tokenGate.classList.add('hidden');
        dashboard.classList.remove('hidden');
        tokenError.classList.add('hidden');
        renderStats(data.stats);
        renderSessions(data.sessions);
        lastUpdated.textContent = `更新于 ${new Date().toLocaleTimeString('zh-CN')}`;
    } catch {
        tokenError.textContent = '无法连接服务器';
        tokenError.classList.remove('hidden');
    }
}

function logout() {
    adminToken = '';
    sessionStorage.removeItem('admin_token');
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
    autoToggle.checked = false;
    autoLabel.classList.add('hidden');
    dashboard.classList.add('hidden');
    tokenGate.classList.remove('hidden');
    tokenInput.value = '';
}

// ── Event Handlers ─────────────────────────────────────────────────────────
tokenForm.addEventListener('submit', e => {
    e.preventDefault();
    login(tokenInput.value.trim());
});

btnRefresh.addEventListener('click', refresh);
btnLogout.addEventListener('click', logout);

autoToggle.addEventListener('change', () => {
    if (autoToggle.checked) {
        autoLabel.classList.remove('hidden');
        autoRefreshTimer = setInterval(refresh, 30000);
    } else {
        autoLabel.classList.add('hidden');
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
});

// ── Init: restore session if token saved ──────────────────────────────────
if (adminToken) {
    login(adminToken);
}

// ── Reset Password Modal ───────────────────────────────────────────────────
const resetModal   = document.getElementById('reset-pwd-modal');
const resetForm    = document.getElementById('reset-pwd-form');
const resetErrDiv  = document.getElementById('reset-pwd-error');
const resetOkDiv   = document.getElementById('reset-pwd-ok');
const resetCancel  = document.getElementById('reset-pwd-cancel');
const resetTarget  = document.getElementById('reset-target-username');

function openResetModal(username) {
    resetTarget.textContent = username;
    resetForm.reset();
    resetErrDiv.classList.add('hidden');
    resetOkDiv.classList.add('hidden');
    resetModal._targetUsername = username;
    resetModal.classList.remove('hidden');
    resetModal.classList.add('flex');
}

function closeResetModal() {
    resetModal.classList.add('hidden');
    resetModal.classList.remove('flex');
}

resetCancel.addEventListener('click', closeResetModal);
resetModal.addEventListener('click', e => { if (e.target === resetModal) closeResetModal(); });

resetForm.addEventListener('submit', async e => {
    e.preventDefault();
    resetErrDiv.classList.add('hidden');
    resetOkDiv.classList.add('hidden');
    const username = resetModal._targetUsername;
    const newPwd = document.getElementById('reset-new-pwd').value;
    try {
        const resp = await fetch('/api/admin/reset-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Admin-Token': adminToken },
            body: JSON.stringify({ username, new_password: newPwd }),
        });
        const data = await resp.json();
        if (resp.ok) {
            resetOkDiv.textContent = `已为 ${username} 重置密码`;
            resetOkDiv.classList.remove('hidden');
            resetForm.reset();
            setTimeout(closeResetModal, 1500);
        } else {
            resetErrDiv.textContent = data.detail || '重置失败';
            resetErrDiv.classList.remove('hidden');
        }
    } catch {
        resetErrDiv.textContent = '网络错误，请重试';
        resetErrDiv.classList.remove('hidden');
    }
});
