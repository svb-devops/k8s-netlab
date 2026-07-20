/**
 * K8S NetLab - Shared nav identity block
 *
 * Renders the /api/auth/me identity state into a container element, shared
 * by landing.js and article.js so both surfaces show the same logged-in /
 * logged-out markup instead of maintaining two near-duplicate copies.
 */

function escapeHtml(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const THEMES = {
    light: {
        username: 'text-gray-600 text-sm',
        cta: 'bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition',
        login: 'text-gray-600 hover:text-gray-900 text-sm transition',
        register: 'bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition',
    },
    dark: {
        username: 'text-devops-muted text-sm font-plex-mono',
        cta: 'bg-k8s-blue hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition',
        login: 'text-devops-muted hover:text-devops-text text-sm transition',
        register: 'bg-k8s-blue hover:bg-blue-500 text-white text-sm px-4 py-1.5 rounded-lg transition',
    },
};

/**
 * Fetch /api/auth/me and render the result into `containerId`.
 *
 * @param {string} containerId - id of the element to fill with nav markup
 * @param {object} [options]
 * @param {'light'|'dark'} [options.theme='light']
 * @param {string} [options.ctaLabel='进入实验室'] - text for the logged-in CTA button
 * @param {string} [options.ctaHref='/app'] - href for the logged-in CTA button
 * @param {(username: string) => void} [options.onAuthenticated] - called with
 *   the username when the user is logged in
 * @returns {Promise<string|null>} the username if authenticated, else null
 */
export async function renderNavAuth(containerId, options = {}) {
    const {
        theme = 'light',
        ctaLabel = '进入实验室',
        ctaHref = '/app',
        onAuthenticated = null,
    } = options;
    const t = THEMES[theme] ?? THEMES.light;
    const container = document.getElementById(containerId);
    if (!container) return null;

    try {
        const r = await fetch('/api/auth/me', { credentials: 'include' });
        if (r.ok) {
            const data = await r.json();
            container.innerHTML = `
                <span class="${t.username}">${escapeHtml(data.username)}</span>
                <a href="${escapeHtml(ctaHref)}" data-lab-nav class="${t.cta}">${escapeHtml(ctaLabel)}</a>
            `;
            if (onAuthenticated) onAuthenticated(data.username);
            return data.username;
        }
        container.innerHTML = `
            <a href="/login.html" class="${t.login}">登录</a>
            <a href="/login.html" class="${t.register}">注册</a>
        `;
        return null;
    } catch (_) {
        return null;
    }
}
