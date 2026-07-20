import { renderNavAuth } from '/js/nav-auth.js';

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

// ---------------------------------------------------------------------------
// Terminal-styled code blocks — cosmetic post-processing only, runs after
// renderMd()'s DOMPurify.sanitize() output is already in the DOM. Only reads
// `.textContent` (never raw HTML) from existing sanitized nodes and only
// re-inserts content that has itself been passed through escapeHtml() before
// any regex-based keyword wrapping, so this cannot reintroduce unescaped
// reader/CMS-controlled markup.
// ---------------------------------------------------------------------------

const _DIAGNOSTIC_KEYWORD_RE = /\b(CrashLoopBackOff|ImagePullBackOff|ErrImagePull|not found|Failed|Error)\b/g;
const _EXIT_CODE_RE = /(Exit Code:\s*)(\d+)/g;

function _highlightDiagnosticText(rawText) {
    // escapeHtml() runs first — every substitution below operates on the
    // already-escaped string, and the keyword/markup inserted is a fixed,
    // hardcoded set of plain ASCII words with no special HTML characters,
    // so this cannot smuggle in unescaped content from rawText.
    let escaped = escapeHtml(rawText);
    escaped = escaped.replace(_EXIT_CODE_RE, '$1<span class="hl-bad">$2</span>');
    escaped = escaped.replace(_DIAGNOSTIC_KEYWORD_RE, '<span class="hl-bad">$1</span>');
    return escaped;
}

function _enhanceCodeBlocks(container) {
    container.querySelectorAll('pre').forEach(pre => {
        const code = pre.querySelector('code');
        if (!code) return;

        const isCommand = code.className.includes('language-bash') || code.className.includes('language-sh');
        if (!isCommand) {
            code.innerHTML = _highlightDiagnosticText(code.textContent);
        }

        const term = document.createElement('div');
        term.className = 'term';

        const bar = document.createElement('div');
        bar.className = 'term-bar';
        ['r', 'y', 'g'].forEach(c => {
            const dot = document.createElement('span');
            dot.className = 'term-dot term-dot-' + c;
            bar.appendChild(dot);
        });
        const label = document.createElement('span');
        label.className = 'term-label';
        label.textContent = isCommand ? '$ kubectl' : 'output';
        bar.appendChild(label);

        pre.parentNode.insertBefore(term, pre);
        term.appendChild(bar);
        term.appendChild(pre);
    });
}

let currentUser = null;

async function initAuth() {
    currentUser = await renderNavAuth('nav-actions', { theme: 'dark' });
}

function renderCommentForm() {
    const area = document.getElementById('comment-form-area');
    if (currentUser) {
        area.innerHTML = `
            <div class="bg-devops-surface rounded-xl border border-devops-border p-5">
                <p class="text-sm text-devops-muted mb-3">以 <strong class="text-devops-text">${escapeHtml(currentUser)}</strong> 身份发表评论</p>
                <textarea id="comment-content" rows="4" placeholder="写下你的想法..."
                    class="w-full bg-devops-bg border border-devops-border-strong rounded-lg px-3 py-2 text-sm text-devops-text placeholder-devops-faint focus:ring-2 focus:ring-k8s-blue focus:border-transparent resize-none"></textarea>
                <div class="flex justify-between items-center mt-3">
                    <span id="comment-msg" class="text-xs text-red-400"></span>
                    <button id="submit-comment"
                        class="bg-k8s-blue hover:bg-blue-500 text-white text-sm font-medium px-5 py-2 rounded-lg transition">
                        发表评论
                    </button>
                </div>
            </div>
        `;
        document.getElementById('submit-comment').addEventListener('click', submitComment);
    } else {
        area.innerHTML = `
            <div class="bg-k8s-blue/10 border border-k8s-blue/25 rounded-xl p-5 text-center">
                <p class="text-devops-text/90 mb-3">请登录后发表评论</p>
                <div class="flex justify-center gap-3">
                    <a href="/login.html" class="text-sm text-k8s-blue hover:underline font-medium">登录</a>
                    <span class="text-devops-border-strong">|</span>
                    <a href="/login.html" class="text-sm text-k8s-blue hover:underline font-medium">注册</a>
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
        list.innerHTML = '<p class="text-devops-faint text-sm">暂无评论，成为第一个评论者吧</p>';
        return;
    }
    list.innerHTML = comments.map(c => `
        <div class="bg-devops-surface rounded-xl border border-devops-border p-5 mb-3">
            <div class="flex items-center justify-between mb-2">
                <span class="font-medium text-devops-text text-sm">${escapeHtml(c.author)}</span>
                <span class="text-xs text-devops-faint font-plex-mono">${formatDate(c.created_at)}</span>
            </div>
            <p class="text-devops-muted text-sm leading-relaxed whitespace-pre-wrap">${escapeHtml(c.content)}</p>
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
            container.innerHTML = '<p class="text-devops-muted">文章不存在</p>';
            return;
        }
        if (!r.ok) throw new Error(r.status);
        const data = await r.json();

        document.title = `${data.title} — K8S NetLab`;
        container.innerHTML = `
            <h1 class="text-3xl font-bold text-white mb-3">${escapeHtml(data.title)}</h1>
            <p class="text-devops-faint text-sm mb-8 font-plex-mono">${formatDate(data.published_at)}</p>
            <div class="prose max-w-none">${renderMd(data.content)}</div>
        `;
        _enhanceCodeBlocks(container);
        _buildToc(container);

        const section = document.getElementById('comments-section');
        section.classList.remove('hidden');
        renderCommentForm();
        renderComments(data.comments || []);

    } catch (e) {
        container.innerHTML = '<p class="text-red-400 text-sm">加载失败，请刷新重试</p>';
    }
}

// ---------------------------------------------------------------------------
// Left sidebar: in-page table of contents, built from the article's own
// `.prose h2` headings after they're already in the (DOMPurify-sanitized)
// DOM. Only ever reads `.textContent` and assigns ids via the safe `.id`
// IDL property / `document.createElement` — never innerHTML of raw text.
// ---------------------------------------------------------------------------

function _slugify(text, index) {
    const base = String(text || '')
        .trim()
        .toLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, '-')
        .replace(/^-+|-+$/g, '');
    return (base || 'section') + '-' + index;
}

function _buildToc(container) {
    const tocNav = document.getElementById('toc-list');
    const tocAside = tocNav ? tocNav.closest('aside') : null;
    if (!tocNav) return;

    const headings = Array.from(container.querySelectorAll('.prose h2'));
    tocNav.innerHTML = '';
    if (headings.length === 0) {
        if (tocAside) tocAside.style.display = 'none';
        return;
    }

    headings.forEach((h, i) => {
        h.id = _slugify(h.textContent, i);
        const link = document.createElement('a');
        link.href = '#' + h.id;
        link.textContent = h.textContent;
        tocNav.appendChild(link);
    });
}

// ---------------------------------------------------------------------------
// Right sidebar: other published articles
// ---------------------------------------------------------------------------

async function loadRelatedArticles() {
    const list = document.getElementById('related-articles-list');
    const aside = list ? list.closest('aside') : null;
    if (!list) return;
    try {
        const r = await fetch('/api/articles');
        if (!r.ok) {
            if (aside) aside.style.display = 'none';
            return;
        }
        const data = await r.json();
        const articles = (data.articles || []).filter(a => a.slug !== slug);
        if (articles.length === 0) {
            if (aside) aside.style.display = 'none';
            return;
        }
        list.innerHTML = articles.map(a => `
            <a href="/article.html?slug=${encodeURIComponent(a.slug)}" class="related-card">
                <p class="text-sm font-medium text-devops-text leading-snug mb-1">${escapeHtml(a.title)}</p>
                <p class="text-xs text-devops-faint font-plex-mono">${formatDate(a.published_at)}</p>
            </a>
        `).join('');
    } catch (_) {
        if (aside) aside.style.display = 'none';
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
    block.className = 'bg-gradient-to-br from-devops-surface to-devops-surface-2 border border-k8s-blue/25 rounded-2xl p-6 my-8';

    // Header row: badge + label
    const header = document.createElement('div');
    header.className = 'flex items-center gap-2 mb-3';
    const badge = document.createElement('span');
    badge.className = 'bg-k8s-blue text-white text-xs font-semibold px-2.5 py-0.5 rounded-full font-plex-mono';
    badge.textContent = '配套实验';
    const label = document.createElement('span');
    label.className = 'text-xs text-blue-300 font-medium';
    label.textContent = '读完这篇，可以立即动手实践';
    header.appendChild(badge);
    header.appendChild(label);

    // Lab title
    const title = document.createElement('h3');
    title.className = 'text-lg font-bold text-white mb-2';
    title.textContent = data.lab_title || '配套实验';

    // Subtitle
    const subtitle = document.createElement('p');
    subtitle.className = 'text-sm text-devops-muted mb-3';
    subtitle.textContent = '无需安装本地环境，在浏览器中直接操练，完成后自动销毁。';

    // Meta row: domain + duration
    const meta = document.createElement('div');
    meta.className = 'flex flex-wrap items-center gap-3 text-xs text-devops-faint mb-5 font-plex-mono';
    if (data.domain) {
        const domainPill = document.createElement('span');
        domainPill.className = 'bg-devops-bg border border-devops-border-strong px-2 py-0.5 rounded-md';
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
    btn.className = 'inline-block bg-k8s-blue hover:bg-blue-500 text-white font-semibold text-sm px-6 py-2.5 rounded-xl transition-colors';
    if (currentUser) {
        btn.href = ctaUrl;
        btn.textContent = data.cta_text || '进入实验';
    } else {
        btn.href = '/login.html?next=' + encodeURIComponent(ctaUrl);
        btn.textContent = '登录后开始实验';
    }

    // Safety note
    const note = document.createElement('p');
    note.className = 'mt-4 text-xs text-devops-faint';
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
    loadRelatedArticles();
});
