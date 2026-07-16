/**
 * Regression tests for article.js's left TOC (_slugify/_buildToc) and right
 * "related articles" sidebar (loadRelatedArticles), added 2026-07-16 after
 * owner asked for the wide empty margins on article.html to be filled with
 * an in-page table of contents (left) and a list of other articles (right).
 *
 * Same vm-sandbox loading approach as test_article_terminal_highlight.mjs —
 * article.js is a plain browser script, not an ES module.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import vm from 'node:vm';

const __dir = dirname(fileURLToPath(import.meta.url));
const articleJsSource = readFileSync(resolve(__dir, '../../frontend/js/article.js'), 'utf-8');
const articleHtmlSource = readFileSync(resolve(__dir, '../../frontend/article.html'), 'utf-8');

function _fakeElement() {
    return {
        innerHTML: '',
        textContent: '',
        style: {},
        classList: { add() {}, remove() {}, toggle() {} },
        addEventListener() {},
        appendChild() {},
        querySelectorAll: () => [],
        querySelector: () => null,
        closest: () => null,
    };
}

function loadSandbox(fetchImpl, search = '') {
    // NOTE: article.js's top-level `const slug = ...` is a lexical binding,
    // not a property of the vm context's global object — setting
    // `sandbox.slug` after the script has run does NOT change what the
    // script's internal functions see. To control `slug`, set `search`
    // *before* the script runs so `slug` is derived correctly at load time.
    const sandbox = {
        URLSearchParams,
        location: { search },
        document: {
            getElementById: () => _fakeElement(),
            querySelector: () => null,
        },
        fetch: fetchImpl || (() => Promise.reject(new Error('no network in test sandbox'))),
        DOMPurify: { sanitize: (s) => s },
        marked: { parse: (s) => s },
        console,
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(articleJsSource, sandbox, { filename: 'article.js' });
    return sandbox;
}

test('_slugify: builds a lowercase hyphenated id from Chinese/English heading text', () => {
    const sandbox = loadSandbox();
    assert.equal(sandbox._slugify('为什么这不是"重启一下就好"', 2), '为什么这不是-重启一下就好-2');
});

test('_slugify: falls back to "section-<index>" for empty/symbol-only headings', () => {
    const sandbox = loadSandbox();
    assert.equal(sandbox._slugify('---', 5), 'section-5');
    assert.equal(sandbox._slugify('', 0), 'section-0');
});

test('_slugify: different indices never collide even for identical heading text', () => {
    const sandbox = loadSandbox();
    const a = sandbox._slugify('修复', 0);
    const b = sandbox._slugify('修复', 1);
    assert.notEqual(a, b);
});

test('_buildToc: assigns a real id (via the safe .id property) to each h2, not innerHTML', () => {
    const sandbox = loadSandbox();
    const headings = [
        { textContent: '症状', id: '' },
        { textContent: '修复思路', id: '' },
    ];
    const tocNav = _fakeElement();
    let appended = [];
    tocNav.appendChild = (el) => appended.push(el);
    sandbox.document.getElementById = (id) => (id === 'toc-list' ? tocNav : _fakeElement());
    sandbox.document.createElement = () => ({ href: '', textContent: '' });
    const container = _fakeElement();
    container.querySelectorAll = (sel) => (sel === '.prose h2' ? headings : []);

    sandbox._buildToc(container);

    assert.equal(headings[0].id, '症状-0');
    assert.equal(headings[1].id, '修复思路-1');
    assert.equal(appended.length, 2);
    assert.equal(appended[0].href, '#症状-0');
    assert.equal(appended[0].textContent, '症状');
});

test('article.html: three-column grid with left TOC and right related-articles asides, hidden below lg', () => {
    assert.ok(articleHtmlSource.includes('lg:grid-cols-[200px_1fr_260px]'));
    assert.ok(articleHtmlSource.includes('id="toc-list"'));
    assert.ok(articleHtmlSource.includes('id="related-articles-list"'));
    // Both sidebars must be responsive (hidden on mobile, shown at lg+) —
    // narrow-viewport readers must not lose reading width to empty sidebars.
    const asideBlocks = articleHtmlSource.match(/<aside class="[^"]*"/g) || [];
    assert.equal(asideBlocks.length, 2, 'expected exactly two <aside> elements');
    asideBlocks.forEach(tag => {
        assert.ok(tag.includes('hidden'), `aside must default to hidden on mobile: ${tag}`);
        assert.ok(tag.includes('lg:block'), `aside must reappear at lg+: ${tag}`);
    });
});

// ---------------------------------------------------------------------------
// loadRelatedArticles — happy path + three degradation paths. Regression for
// a safety-reviewer finding: the `!r.ok` branch originally `return`ed without
// hiding the sidebar, leaving an empty "更多文章" box on screen whenever
// /api/articles responded with a non-2xx status (500/429/etc). Fixed to match
// the fetch-reject and empty-list branches, which already hid it correctly.
// ---------------------------------------------------------------------------

function _wireRelatedArticlesDom(sandbox) {
    const list = _fakeElement();
    const aside = _fakeElement();
    aside.style = {};
    list.closest = (sel) => (sel === 'aside' ? aside : null);
    const appended = [];
    Object.defineProperty(list, 'innerHTML', {
        get() { return appended.join(''); },
        set(v) { appended.push(v); },
    });
    sandbox.document.getElementById = (id) => (id === 'related-articles-list' ? list : _fakeElement());
    return { list, aside };
}

test('loadRelatedArticles: happy path renders cards with escaped titles, excludes current slug', async () => {
    const fetchImpl = () => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
            articles: [
                { slug: 'current', title: 'should be excluded' },
                { slug: 'other', title: '<script>alert(1)</script>', published_at: null },
            ],
        }),
    });
    const sandbox = loadSandbox(fetchImpl, '?slug=current');
    const { list, aside } = _wireRelatedArticlesDom(sandbox);

    await sandbox.loadRelatedArticles();

    assert.ok(!list.innerHTML.includes('should be excluded'), 'current article must be filtered out');
    assert.ok(list.innerHTML.includes('&lt;script&gt;'), 'title must be escaped');
    assert.ok(!list.innerHTML.includes('<script>alert'), 'raw script tag must never reach innerHTML');
    assert.notEqual(aside.style.display, 'none');
});

test('loadRelatedArticles: non-2xx response hides the sidebar (no empty box)', async () => {
    const fetchImpl = () => Promise.resolve({ ok: false, status: 500 });
    const sandbox = loadSandbox(fetchImpl, '?slug=current');
    const { aside } = _wireRelatedArticlesDom(sandbox);

    await sandbox.loadRelatedArticles();

    assert.equal(aside.style.display, 'none');
});

test('loadRelatedArticles: fetch rejection hides the sidebar', async () => {
    const fetchImpl = () => Promise.reject(new Error('network down'));
    const sandbox = loadSandbox(fetchImpl, '?slug=current');
    const { aside } = _wireRelatedArticlesDom(sandbox);

    await sandbox.loadRelatedArticles();

    assert.equal(aside.style.display, 'none');
});

test('loadRelatedArticles: empty article list (only the current article published) hides the sidebar', async () => {
    const fetchImpl = () => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ articles: [{ slug: 'current', title: 'only me' }] }),
    });
    const sandbox = loadSandbox(fetchImpl, '?slug=current');
    const { aside } = _wireRelatedArticlesDom(sandbox);

    await sandbox.loadRelatedArticles();

    assert.equal(aside.style.display, 'none');
});
