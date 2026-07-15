import { LabGenClient, LabGenApiError } from '/js/labgenClient.js';
import { renderLabCatalog, renderErrorState, renderLoading } from '/js/labgenViews.js';

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

    try {
        const labs = await client.listLabs();
        root.innerHTML = renderLabCatalog(labs);
    } catch (e) {
        root.innerHTML = renderErrorState(
            e instanceof LabGenApiError ? e.message : 'Failed to load labs.', 'dark'
        );
    }
}

init();
