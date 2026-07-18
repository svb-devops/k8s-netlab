/**
 * Lab Session Page — Init
 *
 * Layout: full-width kubectl terminal (main area) + left slide-in drawer
 * for step progress, background, and action buttons.
 *
 * DOM architecture:
 *   <header>  — lab title, status badge, drawer toggle
 *   <main>    — full-height kubectl terminal (or loading/error message)
 *   #lab-drawer — step list, progress bar, step pills, background tab,
 *                 fixed footer with 检查当前步骤 / 完成实验 / 中止实验
 */

import { LabGenClient, LabGenApiError } from '/js/labgenClient.js';
import {
    renderSessionView,
    getSessionActionStates,
    renderErrorState,
    renderLoading,
} from '/js/labgenViews.js';
import { LabKubectlTerminal } from '/js/labgen-kubectl-terminal.js';
import { isSessionActive } from '/js/labgen-session-state.js';
import { escapeHtml } from '/js/labgenSecurity.js';

// ── DOM refs ──────────────────────────────────────────────────────────────────

const labTitleEl      = document.getElementById('session-lab-title');
const statusBadgeEl   = document.getElementById('session-status-badge');
const usernameEl      = document.getElementById('session-username');

const messageArea     = document.getElementById('session-message-area');
const messageTextEl   = document.getElementById('session-message-text');
const terminalPanel   = document.getElementById('kubectl-terminal-panel');
const nsBadge         = document.getElementById('kubectl-terminal-ns-badge');

const drawer          = document.getElementById('lab-drawer');
const backdrop        = document.getElementById('lab-drawer-backdrop');
const btnToggleDrawer = document.getElementById('btn-toggle-drawer');
const btnCloseDrawer  = document.getElementById('btn-close-drawer');

const tabSteps        = document.getElementById('drawer-tab-steps');
const tabBackground   = document.getElementById('drawer-tab-background');
const drawerSteps     = document.getElementById('drawer-steps-content');
const drawerBg        = document.getElementById('drawer-background-content');

const progressText    = document.getElementById('drawer-progress-text');
const progressBar     = document.getElementById('drawer-progress-bar');
const stepPills       = document.getElementById('drawer-step-pills');

const btnCheckStep    = document.getElementById('btn-check-step');
const btnComplete     = document.getElementById('btn-complete');
const btnAbort        = document.getElementById('btn-abort');
const actionErrorEl   = document.getElementById('action-error');

// ── Module state ──────────────────────────────────────────────────────────────

let _client    = null;
let _sessionId = null;
let _terminal  = null;
let _wasActive = false;
let _snapshot  = null;   // last loaded snapshot
let _drawerOpen = false;
let _currentTab = 'steps';   // 'steps' | 'background'
let _hasAutoOpenedDrawer = false;

// Matches the #lab-drawer mobile breakpoint in labgen-session.html — below this
// width the drawer is a full-screen overlay, so auto-opening it would hide the
// terminal the learner just connected to.
const DESKTOP_DRAWER_BREAKPOINT_PX = 768;

// ── Drawer ────────────────────────────────────────────────────────────────────

// Matches #lab-drawer's `transition: width 0.25s` in labgen-session.html, plus
// a small safety margin. Refitting the terminal must wait until the drawer's
// width transition actually finishes — not when it starts (see _refitAfterDrawerTransition).
const DRAWER_TRANSITION_MS = 250;

function openDrawer() {
    drawer.classList.add('drawer-open');
    backdrop.classList.add('backdrop-visible');
    _drawerOpen = true;
    _refitAfterDrawerTransition();
}

function closeDrawer() {
    drawer.classList.remove('drawer-open');
    backdrop.classList.remove('backdrop-visible');
    _drawerOpen = false;
    _refitAfterDrawerTransition();
}

// #lab-drawer resizing the terminal (desktop sidebar) is a CSS transition, not
// an instant layout change; calling _terminal.fit() synchronously on toggle (the
// original approach) measured the container mid-transition and gave xterm.js a
// stale column count, corrupting line-wrapping for the rest of the session
// (e.g. later output silently overwriting characters instead of wrapping
// cleanly). A `transitionend` listener fixes the common case, but never fires
// at all under `prefers-reduced-motion` or any other 0-duration transition (the
// CSS Transitions spec doesn't dispatch transitionend for zero-length
// transitions) — for those users fit() would then never run again, which is
// worse than the original bug. setTimeout matching the transition duration
// fires unconditionally regardless of whether the CSS transition actually ran.
function _refitAfterDrawerTransition() {
    setTimeout(() => {
        if (_terminal) _terminal.fit();
    }, DRAWER_TRANSITION_MS + 10);
}

function switchTab(tab) {
    _currentTab = tab;
    const isSteps = tab === 'steps';

    drawerSteps.classList.toggle('hidden', !isSteps);
    drawerBg.classList.toggle('hidden', isSteps);

    tabSteps.classList.toggle('border-k8s-blue', isSteps);
    tabSteps.classList.toggle('text-k8s-blue', isSteps);
    tabSteps.classList.toggle('bg-devops-surface-2', isSteps);
    tabSteps.classList.toggle('border-transparent', !isSteps);
    tabSteps.classList.toggle('text-devops-muted', !isSteps);

    tabBackground.classList.toggle('border-k8s-blue', !isSteps);
    tabBackground.classList.toggle('text-k8s-blue', !isSteps);
    tabBackground.classList.toggle('bg-devops-surface-2', !isSteps);
    tabBackground.classList.toggle('border-transparent', isSteps);
    tabBackground.classList.toggle('text-devops-muted', isSteps);
}

btnToggleDrawer.addEventListener('click', () => _drawerOpen ? closeDrawer() : openDrawer());
btnCloseDrawer.addEventListener('click', closeDrawer);
backdrop.addEventListener('click', closeDrawer);
tabSteps.addEventListener('click', () => switchTab('steps'));
tabBackground.addEventListener('click', () => switchTab('background'));

// ── Initialisation ────────────────────────────────────────────────────────────

async function init() {
    _client = new LabGenClient();

    const me = await _client.getMe();
    if (!me) {
        window.location.href = '/login.html?next=' + encodeURIComponent(window.location.href);
        return;
    }
    usernameEl.textContent = me.username;

    _sessionId = new URLSearchParams(window.location.search).get('sessionId');
    if (!_sessionId) {
        showPageMessage('缺少 sessionId 参数，无法加载实验。', 'error');
        return;
    }

    await loadSnapshot();
}

// ── Snapshot ──────────────────────────────────────────────────────────────────

async function loadSnapshot() {
    try {
        const snapshot = await _client.getSessionSnapshot(_sessionId);
        _snapshot = snapshot;
        _updateHeader(snapshot);
        _updateDrawerContent(snapshot);
        _updateActionButtons(snapshot);
        _syncTerminal(snapshot);
    } catch (e) {
        const msg = e instanceof LabGenApiError && e.status === 404
            ? '实验 Session 不存在'
            : e instanceof LabGenApiError ? e.message : '加载实验环境失败';
        showPageMessage(msg, 'error');
    }
}

// ── Header updates ────────────────────────────────────────────────────────────

function _updateHeader(snapshot) {
    if (snapshot?.title) {
        labTitleEl.textContent = snapshot.title;
        document.title = `${snapshot.title} — K8S NetLab`;
    }
    statusBadgeEl.innerHTML = _statusBadgeHtml(snapshot?.session_state);
}

// ── Drawer content ────────────────────────────────────────────────────────────

function _updateDrawerContent(snapshot) {
    // Steps view
    drawerSteps.innerHTML = renderSessionView(snapshot);

    // Background view
    const bg = snapshot?.experiment_background ?? snapshot?.background ?? '';
    drawerBg.innerHTML = bg
        ? `<p class="text-sm text-devops-text/90 leading-relaxed font-plex">${escapeHtml(bg)}</p>`
        : `<p class="text-sm text-devops-faint text-center pt-12 font-plex">暂无实验背景介绍</p>`;

    // Progress bar + step pills
    _updateProgress(snapshot);
}

function _updateProgress(snapshot) {
    const steps = Array.isArray(snapshot?.steps) ? snapshot.steps : [];
    const total = steps.length;
    const done  = steps.filter(s => s?.status === 'passed').length;
    const pct   = total > 0 ? Math.round((done / total) * 100) : 0;

    progressText.textContent = `${done}/${total} 完成`;
    progressBar.style.width  = `${pct}%`;

    stepPills.innerHTML = steps.map((s, idx) => {
        const isPassed  = s?.status === 'passed';
        const isCurrent = s?.is_current === true;
        const cls = isPassed  ? 'step-pill sp-done'
                  : isCurrent ? 'step-pill sp-active'
                              : 'step-pill';
        const icon = isPassed ? '✓ ' : isCurrent ? '→ ' : `${idx + 1} `;
        return `<button class="${cls}" data-step-idx="${idx}" title="${escapeHtml(s?.title ?? '')}">${icon}步骤 ${idx + 1}</button>`;
    }).join('');

    stepPills.querySelectorAll('[data-step-idx]').forEach(pill => {
        pill.addEventListener('click', () => {
            if (!_drawerOpen) openDrawer();
            switchTab('steps');
            const idx    = parseInt(pill.dataset.stepIdx, 10);
            const stepEl = drawerSteps.querySelectorAll('[data-step-status]')[idx];
            if (stepEl) stepEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    });
}

// ── Action button state ────────────────────────────────────────────────────────

function _updateActionButtons(snapshot) {
    const { canCheck, canComplete, canAbort, readyToComplete } = getSessionActionStates(snapshot);

    _applyBtnState(btnCheckStep, canCheck,    'btn-check', '检查当前步骤');
    _applyBtnState(btnComplete,  canComplete, 'btn-complete', '完成实验');
    _applyBtnState(btnAbort,     canAbort,    'btn-abort', '中止实验');

    btnComplete.dataset.ready = String(readyToComplete);

    actionErrorEl.classList.add('hidden');
    actionErrorEl.textContent = '';
}

function _applyBtnState(btn, enabled, kind, label) {
    btn.disabled     = !enabled;
    btn.textContent  = label;

    if (enabled) {
        if (kind === 'btn-check') {
            btn.className = 'w-full px-4 py-2 rounded text-sm font-medium bg-k8s-blue text-white hover:bg-blue-500 transition';
        } else if (kind === 'btn-complete') {
            btn.className = 'flex-1 px-4 py-2 rounded text-sm font-medium bg-green-600 text-white hover:bg-green-500 transition';
        } else {
            btn.className = 'flex-1 px-4 py-2 rounded text-sm font-medium bg-red-500 text-white hover:bg-red-600 transition';
        }
    } else {
        const full = kind === 'btn-check' ? 'w-full ' : 'flex-1 ';
        btn.className = `${full}px-4 py-2 rounded text-sm font-medium bg-devops-surface-2 text-devops-faint cursor-not-allowed transition`;
    }
}

// ── Terminal sync ─────────────────────────────────────────────────────────────

const _STATE_LABELS = {
    LAB_COMPLETED:      '实验已完成',
    LAB_CLOSED:         '实验已结束',
    LAB_ABORTED:        '实验已中止',
    LAB_CLEANUP_FAILED: '清理失败，请联系管理员',
    IMAGE_CHECK_RUNNING:'正在检查镜像，请稍候…',
};

function _syncTerminal(snapshot) {
    const isActive = isSessionActive(snapshot);

    if (isActive) {
        messageArea.classList.add('hidden');
        terminalPanel.classList.remove('hidden');
        terminalPanel.classList.add('flex');

        if (!_terminal) {
            // Decide up front whether this activation is about to auto-open the
            // drawer (see block below) — if so, the terminal must not open its
            // WebSocket (and therefore must not write anything) until that
            // transition has settled, or the drawer's delayed refit silently
            // corrupts/loses whatever was already written. See the connect()
            // docstring in labgen-kubectl-terminal.js for the full bug history.
            const willAutoOpenDrawer = !_hasAutoOpenedDrawer
                && !_drawerOpen
                && window.innerWidth >= DESKTOP_DRAWER_BREAKPOINT_PX;

            _terminal = new LabKubectlTerminal(_sessionId, 'kubectl-terminal-container');
            _terminal.connect(willAutoOpenDrawer ? DRAWER_TRANSITION_MS + 10 : 0);
            _wasActive = true;
        }

        // First time the terminal becomes active: surface the step instructions
        // by default on desktop, since the toggle button alone is easy to miss
        // and the drawer no longer covers the terminal (it resizes it instead).
        if (!_hasAutoOpenedDrawer) {
            _hasAutoOpenedDrawer = true;
            if (!_drawerOpen && window.innerWidth >= DESKTOP_DRAWER_BREAKPOINT_PX) {
                openDrawer();
            }
        }

        if (snapshot?.namespace && nsBadge) {
            nsBadge.textContent = snapshot.namespace;
            nsBadge.classList.remove('hidden');
        }
    } else {
        if (_terminal && _wasActive) {
            _terminal.disconnect();
            _terminal  = null;
            _wasActive = false;
        }
        terminalPanel.classList.add('hidden');
        terminalPanel.classList.remove('flex');
        messageArea.classList.remove('hidden');
        messageTextEl.textContent = _STATE_LABELS[snapshot?.session_state] ?? '正在准备实验环境…';
        messageTextEl.className   = snapshot?.session_state === 'LAB_CLEANUP_FAILED'
            ? 'text-red-400 text-sm font-plex'
            : 'text-devops-muted text-sm font-plex';
    }
}

// ── Action button event listeners ─────────────────────────────────────────────

btnCheckStep.addEventListener('click', async () => {
    if (btnCheckStep.disabled) return;
    btnCheckStep.disabled    = true;
    btnCheckStep.textContent = '检查中…';
    _clearActionError();
    try {
        const currentStepId = _snapshot?.current_step_id ?? '';
        await _client.checkStep(_sessionId, currentStepId);
        await loadSnapshot();
    } catch (e) {
        _showActionError(e);
        // Restore button from snapshot state
        if (_snapshot) _updateActionButtons(_snapshot);
    }
});

btnComplete.addEventListener('click', async () => {
    if (btnComplete.disabled) return;
    btnComplete.disabled    = true;
    btnComplete.textContent = '完成中…';
    _clearActionError();
    try {
        await _client.completeSession(_sessionId);
        await loadSnapshot();
    } catch (e) {
        _showActionError(e);
        if (_snapshot) _updateActionButtons(_snapshot);
    }
});

btnAbort.addEventListener('click', async () => {
    if (btnAbort.disabled) return;
    if (!confirm('确认中止实验？此操作不可撤销，实验进度将清除。')) return;
    btnAbort.disabled    = true;
    btnAbort.textContent = '中止中…';
    _clearActionError();
    try {
        await _client.abortSession(_sessionId);
        await loadSnapshot();
    } catch (e) {
        _showActionError(e);
        if (_snapshot) _updateActionButtons(_snapshot);
    }
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function showPageMessage(text, type = 'info') {
    messageArea.classList.remove('hidden');
    terminalPanel.classList.add('hidden');
    terminalPanel.classList.remove('flex');
    messageTextEl.textContent = text;
    messageTextEl.className   = type === 'error' ? 'text-red-400 text-sm font-plex' : 'text-devops-muted text-sm font-plex';
}

function _showActionError(e) {
    const msg = e instanceof LabGenApiError ? e.message : '操作失败，请重试';
    actionErrorEl.textContent = msg;
    actionErrorEl.classList.remove('hidden');
}

function _clearActionError() {
    actionErrorEl.classList.add('hidden');
    actionErrorEl.textContent = '';
}

const _STATUS_CLASSES = {
    LAB_ACTIVE:          'bg-green-500/15 text-green-400 border border-green-500/30',
    LAB_COMPLETED:       'bg-k8s-blue/15 text-blue-400 border border-blue-500/30',
    LAB_CLOSED:          'bg-devops-surface-2 text-devops-muted border border-devops-border-strong',
    LAB_ABORTED:         'bg-red-500/15 text-red-400 border border-red-500/30',
    LAB_CLEANUP_FAILED:  'bg-orange-500/15 text-orange-400 border border-orange-500/30',
    IMAGE_CHECK_RUNNING: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
};

function _statusBadgeHtml(status) {
    const cls = _STATUS_CLASSES[status] ?? 'bg-devops-surface-2 text-devops-muted border border-devops-border-strong';
    return `<span class="inline-block px-2 py-0.5 rounded text-xs font-plex-mono font-medium ${cls}">${escapeHtml(status ?? 'UNKNOWN')}</span>`;
}

// ── Boot ──────────────────────────────────────────────────────────────────────

init();
