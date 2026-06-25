const slug = new URLSearchParams(location.search).get('slug');

function escapeHtml(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function formatDate(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString('zh-CN', {year:'numeric', month:'long', day:'numeric', hour:'2-digit', minute:'2-digit'});
}
function renderMd(md) {
    return DOMPurify.sanitize(marked.parse(md || ''));
}

let currentUser = null;

async function initAuth() {
    try {
        const r = await fetch('/api/auth/me', {credentials:'include'});
        const nav = document.getElementById('nav-actions');
        if (r.ok) {
            const data = await r.json();
            currentUser = data.username;
            nav.innerHTML = `
                <span class="text-gray-600 text-sm">${escapeHtml(data.username)}</span>
                <a href="/app" data-lab-nav class="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition">进入实验室</a>
            `;
        } else {
            nav.innerHTML = `
                <a href="/login.html" class="text-gray-600 hover:text-gray-900 text-sm transition">登录</a>
                <a href="/login.html" class="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition">注册</a>
            `;
        }
    } catch (_) {}
}

function renderCommentForm() {
    const area = document.getElementById('comment-form-area');
    if (currentUser) {
        area.innerHTML = `
            <div class="bg-white rounded-xl border border-gray-200 p-5">
                <p class="text-sm text-gray-500 mb-3">以 <strong>${escapeHtml(currentUser)}</strong> 身份发表评论</p>
                <textarea id="comment-content" rows="4" placeholder="写下你的想法..."
                    class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"></textarea>
                <div class="flex justify-between items-center mt-3">
                    <span id="comment-msg" class="text-xs text-red-500"></span>
                    <button id="submit-comment"
                        class="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-5 py-2 rounded-lg transition">
                        发表评论
                    </button>
                </div>
            </div>
        `;
        document.getElementById('submit-comment').addEventListener('click', submitComment);
    } else {
        area.innerHTML = `
            <div class="bg-blue-50 border border-blue-200 rounded-xl p-5 text-center">
                <p class="text-gray-700 mb-3">请登录后发表评论</p>
                <div class="flex justify-center gap-3">
                    <a href="/login.html" class="text-sm text-blue-600 hover:underline font-medium">登录</a>
                    <span class="text-gray-300">|</span>
                    <a href="/login.html" class="text-sm text-blue-600 hover:underline font-medium">注册</a>
                </div>
            </div>
        `;
    }
}

async function submitComment() {
    const content = document.getElementById('comment-content').value.trim();
    const msg = document.getElementById('comment-msg');
    if (!content) { msg.textContent = '评论不能为空'; return; }

    const btn = document.getElementById('submit-comment');
    btn.disabled = true;
    btn.textContent = '提交中...';
    msg.textContent = '';

    try {
        const r = await fetch(`/api/articles/${encodeURIComponent(slug)}/comments`, {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            credentials: 'include',
            body: JSON.stringify({content}),
        });
        if (r.status === 401) {
            msg.textContent = '请先登录';
        } else if (!r.ok) {
            const d = await r.json();
            msg.textContent = d.detail || '提交失败';
        } else {
            document.getElementById('comment-content').value = '';
            await loadComments();
        }
    } catch (_) {
        msg.textContent = '网络错误，请重试';
    } finally {
        btn.disabled = false;
        btn.textContent = '发表评论';
    }
}

function renderComments(comments) {
    const list = document.getElementById('comments-list');
    if (!comments.length) {
        list.innerHTML = '<p class="text-gray-400 text-sm">暂无评论，成为第一个评论者吧</p>';
        return;
    }
    list.innerHTML = comments.map(c => `
        <div class="bg-white rounded-xl border border-gray-200 p-5 mb-3">
            <div class="flex items-center justify-between mb-2">
                <span class="font-medium text-gray-900 text-sm">${escapeHtml(c.author)}</span>
                <span class="text-xs text-gray-400">${formatDate(c.created_at)}</span>
            </div>
            <p class="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap">${escapeHtml(c.content)}</p>
        </div>
    `).join('');
}

async function loadComments() {
    try {
        const r = await fetch(`/api/articles/${encodeURIComponent(slug)}`);
        if (r.ok) {
            const data = await r.json();
            renderComments(data.comments || []);
        }
    } catch (_) {}
}

async function loadArticle() {
    const container = document.getElementById('article-container');
    if (!slug) {
        container.innerHTML = '<p class="text-red-400">未指定文章</p>';
        return;
    }
    try {
        const r = await fetch(`/api/articles/${encodeURIComponent(slug)}`);
        if (r.status === 404) {
            container.innerHTML = '<p class="text-gray-500">文章不存在</p>';
            return;
        }
        if (!r.ok) throw new Error(r.status);
        const data = await r.json();

        document.title = `${data.title} — K8S NetLab`;
        container.innerHTML = `
            <h1 class="text-3xl font-bold text-gray-900 mb-3">${escapeHtml(data.title)}</h1>
            <p class="text-gray-400 text-sm mb-8">${formatDate(data.published_at)}</p>
            <div class="prose max-w-none">${renderMd(data.content)}</div>
        `;

        const section = document.getElementById('comments-section');
        section.classList.remove('hidden');
        renderCommentForm();
        renderComments(data.comments || []);

    } catch (e) {
        container.innerHTML = '<p class="text-red-400 text-sm">加载失败，请刷新重试</p>';
    }
}

// ---------------------------------------------------------------------------
// Lab CTA block — rendered when article has a linked published lab
// ---------------------------------------------------------------------------

async function loadLabCTA() {
    const container = document.getElementById('lab-cta-container');
    if (!container || !slug) return;
    try {
        const r = await fetch(`/api/articles/${encodeURIComponent(slug)}/lab-cta`);
        if (!r.ok) return;
        const data = await r.json();
        if (!data.has_cta) return;
        renderLabCTA(container, data);
    } catch (_) {
        // Silent: no CTA is the safe fallback; never surface internal errors to reader
        console.debug('[LabCTA] no CTA available or fetch failed');
    }
}

function _validateCtaUrl(raw) {
    // Only allow our own lab deep links — reject anything else
    if (typeof raw === 'string' && raw.startsWith('/labgen-lab.html?labId=')) return raw;
    return null;
}

function renderLabCTA(container, data) {
    const ctaUrl = _validateCtaUrl(data.cta_url);
    if (!ctaUrl) {
        console.debug('[LabCTA] cta_url did not pass validation, skipping render');
        return;
    }

    const block = document.createElement('div');
    block.id = 'lab-cta-block';
    block.className = 'bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 rounded-2xl p-6 my-8';

    // Header row: badge + label
    const header = document.createElement('div');
    header.className = 'flex items-center gap-2 mb-3';
    const badge = document.createElement('span');
    badge.className = 'bg-blue-600 text-white text-xs font-semibold px-2.5 py-0.5 rounded-full';
    badge.textContent = '配套实验';
    const label = document.createElement('span');
    label.className = 'text-xs text-blue-700 font-medium';
    label.textContent = '读完这篇，可以立即动手实践';
    header.appendChild(badge);
    header.appendChild(label);

    // Lab title
    const title = document.createElement('h3');
    title.className = 'text-lg font-bold text-gray-900 mb-2';
    title.textContent = data.lab_title || '配套实验';

    // Subtitle
    const subtitle = document.createElement('p');
    subtitle.className = 'text-sm text-gray-600 mb-3';
    subtitle.textContent = '无需安装本地环境，在浏览器中直接操练，完成后自动销毁。';

    // Meta row: domain + duration
    const meta = document.createElement('div');
    meta.className = 'flex flex-wrap items-center gap-3 text-xs text-gray-500 mb-5';
    if (data.domain) {
        const domainPill = document.createElement('span');
        domainPill.className = 'bg-white border border-gray-200 px-2 py-0.5 rounded-md';
        domainPill.textContent = data.domain.toUpperCase();
        meta.appendChild(domainPill);
    }
    if (data.estimated_duration) {
        const dur = document.createElement('span');
        dur.textContent = '约 ' + data.estimated_duration + ' 分钟';
        meta.appendChild(dur);
    }

    // CTA button
    const btn = document.createElement('a');
    btn.className = 'inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold text-sm px-6 py-2.5 rounded-xl transition-colors';
    if (currentUser) {
        btn.href = ctaUrl;
        btn.textContent = data.cta_text || '进入实验';
    } else {
        btn.href = '/login.html?next=' + encodeURIComponent(ctaUrl);
        btn.textContent = '登录后开始实验';
    }

    // Safety note
    const note = document.createElement('p');
    note.className = 'mt-4 text-xs text-gray-400';
    note.textContent = data.sandbox_note || '实验运行在临时隔离环境中，完成后自动销毁。';

    block.appendChild(header);
    block.appendChild(title);
    block.appendChild(subtitle);
    block.appendChild(meta);
    block.appendChild(btn);
    block.appendChild(note);

    container.appendChild(block);

    // Unify header nav with embedded CTA so article page has one lab entry point
    const navLabLink = document.querySelector('#nav-actions [data-lab-nav]');
    if (navLabLink) {
        navLabLink.href = ctaUrl;
        navLabLink.textContent = '进入配套实验';
    }
}

initAuth().then(() => {
    loadArticle();
    loadLabCTA();
});
