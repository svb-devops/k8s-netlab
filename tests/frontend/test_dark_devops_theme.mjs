/**
 * Regression tests for the dark DevOps-style theme applied to the learner-facing
 * lab flow (labgen-catalog.html / labgen-lab.html / labgen-session.html).
 *
 * Owner feedback (2026-07-15): the light Tailwind-default look was "太丑，没办法
 * 放出去". Redesigned to a dark, terminal-inspired palette (near-black surfaces,
 * K8s blue accent, JetBrains Mono for technical labels) consistent with common
 * DevOps tooling (GitHub Dark, Grafana, Kubernetes Dashboard).
 *
 * These tests lock in the dark palette for the render functions that are
 * exclusive to the three in-scope pages (renderLabCatalog, renderLabDetail,
 * renderSessionView) — they must never silently drift back to the old light
 * Tailwind gray/white classes. renderErrorState/renderNotFound/renderLoading
 * are shared with admin/dev-only views, so those are tested via their
 * `theme='dark'` opt-in path, and their light-mode (default) behavior is
 * asserted separately to prove admin/dev pages are unaffected.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));
const {
    renderLabCatalog,
    renderLabDetail,
    renderSessionView,
    renderErrorState,
    renderNotFound,
    renderLoading,
} = await import(resolve(__dir, '../../frontend/js/labgenViews.js'));

// ─── renderLabCatalog ──────────────────────────────────────────────────────

test('renderLabCatalog: uses dark devops surface/border tokens, not light gray', () => {
    const html = renderLabCatalog([
        { lab_id: 'l1', title: 'Test Lab', summary: 'desc', is_startable: true, objective_count: 2, step_count: 3 },
    ]);
    assert.ok(html.includes('bg-devops-surface'), 'card must use dark surface token');
    assert.ok(html.includes('text-devops-text'), 'title must use dark text token');
    assert.ok(!html.includes('border-gray-200'), 'must not keep the old light card border');
    assert.ok(!html.includes('bg-white'), 'must not keep a light card background');
});

// ─── renderLabDetail ───────────────────────────────────────────────────────

test('renderLabDetail: uses dark devops tokens for the heading and body text', () => {
    const html = renderLabDetail({
        lab: { title: 'Detail Lab', summary: 'sum', objectives: ['obj1'], steps_preview: [] },
        eligibility: { is_startable: true },
    });
    assert.ok(html.includes('text-devops-text'), 'heading must use dark text token');
    assert.ok(html.includes('text-devops-muted'), 'summary must use dark muted token');
    assert.ok(!html.includes('text-gray-900'), 'must not keep the old light heading color');
    assert.ok(!html.includes('text-gray-600'), 'must not keep the old light summary color');
});

test('renderLabDetail: ineligible alert box uses dark red tokens', () => {
    const html = renderLabDetail({
        lab: { title: 'Detail Lab' },
        eligibility: { is_startable: false, issues: [{ severity: 'error', message: 'blocked' }] },
    });
    assert.ok(html.includes('bg-red-500/10'), 'ineligible alert must use dark translucent red');
    assert.ok(!html.includes('bg-red-50 '), 'must not keep the old light red alert background');
});

// ─── renderSessionView ─────────────────────────────────────────────────────

test('renderSessionView: step cards and status badge use dark devops tokens', () => {
    const html = renderSessionView({
        session_state: 'LAB_ACTIVE',
        title: 'Session Lab',
        steps: [{ step_id: 's1', title: 'Step 1', status: 'passed', is_current: false }],
    });
    assert.ok(html.includes('bg-devops-surface'), 'step card must use dark surface token');
    assert.ok(html.includes('border-green-500/30'), 'status badge must use dark translucent green');
    assert.ok(!html.includes('bg-green-100'), 'must not keep the old light green badge background');
});

test('renderSessionView: missing snapshot renders the dark error state', () => {
    const html = renderSessionView(null);
    assert.ok(html.includes('bg-red-500/10'), 'must render the dark error state, not the light default');
});

// ─── Shared error/loading/notfound: dark opt-in vs light default ──────────

test('renderErrorState: dark theme opt-in uses devops tokens', () => {
    const html = renderErrorState('boom', 'dark');
    assert.ok(html.includes('bg-red-500/10'));
    assert.ok(!html.includes('bg-red-50 '));
});

test('renderErrorState: default (no theme arg) stays light — admin/dev pages unaffected', () => {
    const html = renderErrorState('boom');
    assert.ok(html.includes('bg-red-50'), 'default call sites (admin/dev views) must keep the original light styling');
});

test('renderNotFound: dark theme opt-in uses devops tokens', () => {
    const html = renderNotFound('Lab', 'dark');
    assert.ok(html.includes('bg-devops-surface'));
});

test('renderNotFound: default (no theme arg) stays light', () => {
    const html = renderNotFound('Lab');
    assert.ok(html.includes('bg-gray-50'));
});

test('renderLoading: dark theme opt-in uses devops tokens', () => {
    const html = renderLoading('dark');
    assert.ok(html.includes('text-devops-muted'));
});

test('renderLoading: default (no theme arg) stays light', () => {
    const html = renderLoading();
    assert.ok(html.includes('text-gray-500'));
});
