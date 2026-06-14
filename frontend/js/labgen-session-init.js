import { LabGenClient, LabGenApiError } from '/js/labgenClient.js';
import { renderSessionView, renderErrorState, renderNotFound, renderLoading } from '/js/labgenViews.js';

const root = document.getElementById('root');
const devInfo = document.getElementById('dev-user-info');
let _client;
let _sessionId;

async function init() {
    root.innerHTML = renderLoading();

    _client = new LabGenClient();
    const me = await _client.getMe();
    if (!me) {
        window.location.href = '/login.html?next=' + encodeURIComponent(window.location.href);
        return;
    }
    devInfo.textContent = me.username;

    _sessionId = new URLSearchParams(window.location.search).get('sessionId');
    if (!_sessionId) {
        root.innerHTML = renderErrorState('Missing ?sessionId= parameter.');
        return;
    }

    await loadSnapshot();
}

async function loadSnapshot() {
    try {
        const snapshot = await _client.getSessionSnapshot(_sessionId);
        root.innerHTML = renderSessionView(snapshot);
        attachActions(snapshot);
    } catch (e) {
        if (e instanceof LabGenApiError && e.status === 404) {
            root.innerHTML = renderNotFound('Session');
        } else {
            root.innerHTML = renderErrorState(
                e instanceof LabGenApiError ? e.message : 'Failed to load session.'
            );
        }
    }
}

function attachActions(snapshot) {
    const checkBtn = root.querySelector('[data-action="check-step"]');
    if (checkBtn && !checkBtn.disabled) {
        checkBtn.addEventListener('click', async () => {
            checkBtn.disabled = true;
            checkBtn.textContent = 'Checking…';
            try {
                await _client.checkStep(_sessionId, snapshot?.current_step_id ?? '');
                await loadSnapshot();
            } catch (e) {
                checkBtn.disabled = false;
                checkBtn.textContent = 'Check Current Step';
                showInlineError(checkBtn, e);
            }
        });
    }

    const completeBtn = root.querySelector('[data-action="complete"]');
    if (completeBtn && !completeBtn.disabled) {
        completeBtn.addEventListener('click', async () => {
            completeBtn.disabled = true;
            completeBtn.textContent = 'Completing…';
            try {
                await _client.completeSession(_sessionId);
                await loadSnapshot();
            } catch (e) {
                completeBtn.disabled = false;
                completeBtn.textContent = 'Complete Lab';
                showInlineError(completeBtn, e);
            }
        });
    }

    const abortBtn = root.querySelector('[data-action="abort"]');
    if (abortBtn && !abortBtn.disabled) {
        abortBtn.addEventListener('click', async () => {
            if (!confirm('Abort this session? This cannot be undone.')) return;
            abortBtn.disabled = true;
            abortBtn.textContent = 'Aborting…';
            try {
                await _client.abortSession(_sessionId);
                await loadSnapshot();
            } catch (e) {
                abortBtn.disabled = false;
                abortBtn.textContent = 'Abort';
                showInlineError(abortBtn, e);
            }
        });
    }
}

function showInlineError(btn, e) {
    const existing = btn.parentElement.querySelector('.labgen-inline-error');
    if (existing) existing.remove();
    const msg = e instanceof LabGenApiError ? e.message : 'Action failed.';
    const errDiv = document.createElement('p');
    errDiv.className = 'labgen-inline-error text-red-600 text-xs mt-1';
    errDiv.textContent = msg;
    btn.parentElement.appendChild(errDiv);
}

init();
