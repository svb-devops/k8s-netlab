const API = '/api/articles';

function escapeHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('zh-CN', {year:'numeric', month:'long', day:'numeric'});
}

async function initNav() {
    try {
        const r = await fetch('/api/auth/me', {credentials:'include'});
        const nav = document.getElementById('nav-actions');
        const cta = document.getElementById('hero-cta');
        if (r.ok) {
            const data = await r.json();
            nav.innerHTML = `
                <span class="text-gray-600 text-sm">${escapeHtml(data.username)}</span>
                <a href="/app" class="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition">进入实验室</a>
            `;
            cta.href = '/app';
            cta.textContent = '进入实验室';
        } else {
            nav.innerHTML = `
                <a href="/login.html" class="text-gray-600 hover:text-gray-900 text-sm transition">登录</a>
                <a href="/login.html" class="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition">注册</a>
            `;
        }
    } catch (_) {}
}

async function loadArticles() {
    const container = document.getElementById('articles-list');
    try {
        const r = await fetch(API);
        if (!r.ok) throw new Error(r.status);
        const {articles} = await r.json();
        if (!articles.length) {
            container.innerHTML = '<p class="text-gray-400 text-sm">暂无文章</p>';
            return;
        }
        container.innerHTML = articles.map(a => `
            <article class="bg-white rounded-xl border border-gray-200 p-6 mb-4 hover:shadow-md transition cursor-pointer"
                     data-slug="${escapeHtml(a.slug)}">
                <h3 class="text-xl font-bold text-gray-900 mb-2">${escapeHtml(a.title)}</h3>
                ${a.excerpt ? `<p class="text-gray-600 text-sm leading-relaxed mb-3">${escapeHtml(a.excerpt)}</p>` : ''}
                <div class="flex items-center gap-3 text-xs text-gray-400">
                    <span>${formatDate(a.published_at)}</span>
                    <span class="text-blue-600 font-medium">阅读全文 →</span>
                </div>
            </article>
        `).join('');

        container.addEventListener('click', (e) => {
            const article = e.target.closest('article[data-slug]');
            if (article) {
                location.href = '/article.html?slug=' + encodeURIComponent(article.dataset.slug);
            }
        });
    } catch (e) {
        container.innerHTML = '<p class="text-red-400 text-sm">加载失败，请刷新重试</p>';
    }
}

initNav();
loadArticles();
