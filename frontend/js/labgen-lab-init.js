import { LabGenClient, LabGenApiError } from '/js/labgenClient.js';
import { renderLabDetail, renderErrorState, renderNotFound, renderLoading } from '/js/labgenViews.js';

const root = document.getElementById('root');
const devInfo = document.getElementById('dev-user-info');

async function init() {
    root.innerHTML = renderLoading();

    const client = new LabGenClient();
    const me = await client.getMe();
    if (!me) {
        window.location.href = '/login.html?next=' + encodeURIComponent(window.location.href);
        return;
    }
    devInfo.textContent = me.username;

    const labId = new URLSearchParams(window.location.search).get('labId');
    if (!labId) {
        root.innerHTML = renderErrorState('Missing ?labId= parameter.');
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
            root.innerHTML = renderNotFound('Lab');
        } else {
            root.innerHTML = renderErrorState(
                e instanceof LabGenApiError ? e.message : 'Failed to load lab.'
            );
        }
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
            btn.disabled = false;
            btn.textContent = 'Start Lab';
            const msg = e instanceof LabGenApiError ? e.message : 'Failed to start lab.';
            const errDiv = document.createElement('p');
            errDiv.className = 'text-red-600 text-sm mt-2';
            errDiv.textContent = msg;
            btn.insertAdjacentElement('afterend', errDiv);
        }
    });
}

init();
