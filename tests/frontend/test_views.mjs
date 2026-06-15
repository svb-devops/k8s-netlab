/**
 * Tests for frontend/js/labgenViews.js
 * Run with: node --test tests/frontend/test_views.mjs
 *
 * All view functions are pure (return HTML strings), so no jsdom is needed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));
const {
    renderAdminDraftView,
    renderLabCatalog,
    renderLabDetail,
    renderSessionView,
    renderContractPackSummary,
    renderErrorState,
    renderNotFound,
    renderLoading,
} = await import(resolve(__dir, '../../frontend/js/labgenViews.js'));

const { assertNoSensitiveDisplayData } =
    await import(resolve(__dir, '../../frontend/js/labgenSecurity.js'));

// ── Helpers ───────────────────────────────────────────────────────────────────

function hasAttr(html, attr, value) {
    // Matches data-foo="value" or data-foo='value'
    const re = new RegExp(`${attr}=["']?${value}["']?`);
    return re.test(html);
}

function hasDisabled(html, action) {
    // Checks that a button with data-action has disabled attribute
    const re = new RegExp(`data-action=["']${action}["'][^>]*disabled|disabled[^>]*data-action=["']${action}["']`);
    return re.test(html);
}

// ── renderAdminDraftView ──────────────────────────────────────────────────────

const ALLOWED_DECISION = {
    status: 'ALLOWED',
    issues: [],
};
const BLOCKED_DECISION = {
    status: 'BLOCKED',
    issues: [
        { code: 'has_steps', message: 'No steps defined', severity: 'error' },
        { code: 'has_objectives', message: 'Must have at least one objective', severity: 'error' },
    ],
};
const PREVIEW = {
    title: 'K8s Networking Basics',
    summary: 'Learn pod networking fundamentals.',
    objectives: ['Understand pod CIDR', 'Configure NetworkPolicy'],
    steps: [{ step_id: 'step-1', title: 'Create a pod' }],
    validation_issues: [],
};

test('admin view: ALLOWED decision renders publish button enabled', () => {
    const html = renderAdminDraftView({ preview: PREVIEW, decision: ALLOWED_DECISION });
    assert.ok(hasAttr(html, 'data-action', 'publish'), 'Missing publish button');
    assert.ok(hasAttr(html, 'data-publish-enabled', 'true'), 'Button not marked as enabled');
    assert.ok(!hasDisabled(html, 'publish'), 'Publish button should NOT be disabled');
});

test('admin view: BLOCKED decision renders publish button disabled', () => {
    const html = renderAdminDraftView({ preview: PREVIEW, decision: BLOCKED_DECISION });
    assert.ok(hasAttr(html, 'data-publish-enabled', 'false'), 'Button should be marked not enabled');
    assert.ok(hasDisabled(html, 'publish'), 'Publish button must be disabled');
});

test('admin view: BLOCKED shows blocked reasons', () => {
    const html = renderAdminDraftView({ preview: PREVIEW, decision: BLOCKED_DECISION });
    assert.ok(html.includes('No steps defined'), 'Missing blocked reason');
    assert.ok(html.includes('Must have at least one objective'), 'Missing second blocked reason');
});

test('admin view: does not render raw_model_output', () => {
    const preview = { ...PREVIEW, raw_model_output: '{"model":"gpt-5","choices":[{"text":"..."}]}' };
    const html = renderAdminDraftView({ preview, decision: ALLOWED_DECISION });
    assert.ok(!html.includes('gpt-5'), 'raw_model_output must not appear in output');
    assert.ok(!html.includes('raw_model_output'), 'raw_model_output field name must not appear');
});

test('admin view: does not render hidden_prompt', () => {
    const preview = { ...PREVIEW, hidden_prompt: 'You are a lab generator...' };
    const html = renderAdminDraftView({ preview, decision: ALLOWED_DECISION });
    assert.ok(!html.includes('You are a lab generator'), 'hidden_prompt must not appear');
});

test('admin view: title is included in output', () => {
    const html = renderAdminDraftView({ preview: PREVIEW, decision: ALLOWED_DECISION });
    assert.ok(html.includes('K8s Networking Basics'));
});

// ── renderLabCatalog ──────────────────────────────────────────────────────────

test('catalog: renders only provided labs', () => {
    const labs = [
        { lab_id: 'lab-1', title: 'Intro Lab', is_startable: true, objective_count: 2, step_count: 3 },
        { lab_id: 'lab-2', title: 'Advanced Lab', is_startable: false, objective_count: 5, step_count: 7 },
    ];
    const html = renderLabCatalog(labs);
    assert.ok(html.includes('Intro Lab'));
    assert.ok(html.includes('Advanced Lab'));
    // startable badge
    assert.ok(html.includes('Startable'), 'Missing Startable badge');
    assert.ok(html.includes('Not available'), 'Missing Not available badge');
});

test('catalog: empty array shows no-labs message', () => {
    const html = renderLabCatalog([]);
    assert.ok(html.includes('No published labs'), 'Missing empty state message');
});

test('catalog: lab card links to /labgen-lab.html?labId=...', () => {
    const html = renderLabCatalog([{ lab_id: 'lab-xyz', title: 'Test Lab' }]);
    assert.ok(html.includes('labgen-lab.html?labId=lab-xyz'), 'Missing detail link');
});

test('catalog: XSS in title is escaped', () => {
    const html = renderLabCatalog([{ lab_id: 'x', title: '<script>alert(1)</script>' }]);
    assert.ok(!html.includes('<script>'), 'XSS not escaped in catalog title');
    assert.ok(html.includes('&lt;script&gt;'), 'XSS not properly escaped');
});

// ── renderLabDetail ───────────────────────────────────────────────────────────

test('lab detail: eligible shows start button enabled', () => {
    const lab = { title: 'Pod Networking', objectives: ['obj1'], steps: [{ step_id: 's1', title: 'Step 1' }] };
    // Backend returns is_startable (not is_eligible) + issues array
    const elig = { is_startable: true, issues: [], checked_at: '2026-06-14T00:00:00Z' };
    const html = renderLabDetail({ lab, eligibility: elig });
    assert.ok(hasAttr(html, 'data-startable', 'true'));
    assert.ok(!hasDisabled(html, 'start-lab'), 'Start button must not be disabled when is_startable=true');
});

test('lab detail: not eligible shows start button disabled', () => {
    const lab = { title: 'Pod Networking', objectives: [], steps: [] };
    // Backend: is_startable=false with error issues
    const elig = { is_startable: false, issues: [{ code: 'NO_VM', message: 'No VM assigned', severity: 'error', source: 'session' }], checked_at: '2026-06-14T00:00:00Z' };
    const html = renderLabDetail({ lab, eligibility: elig });
    assert.ok(hasAttr(html, 'data-startable', 'false'));
    assert.ok(hasDisabled(html, 'start-lab'), 'Start button must be disabled when is_startable=false');
    assert.ok(html.includes('No VM assigned'), 'Ineligible reason not shown');
});

test('lab detail: is_startable=true (not is_eligible) enables Start button', () => {
    const lab = { title: 'Pod Networking', objectives: [], steps: [] };
    // Regression: old code checked is_eligible which does not exist in API
    const elig = { is_startable: true, issues: [], checked_at: '2026-06-14T00:00:00Z' };
    const html = renderLabDetail({ lab, eligibility: elig });
    assert.ok(!hasDisabled(html, 'start-lab'), 'is_startable=true must enable Start (not is_eligible)');
});

test('lab detail: runtime_checks_deferred shows warning', () => {
    const lab = { title: 'Test Lab', objectives: [], steps: [] };
    // Regression: old code checked top-level runtime_checks_deferred which does not exist in API
    // The RUNTIME_CHECKS_DEFERRED code comes inside the issues array
    const elig = { is_startable: true, issues: [{ code: 'RUNTIME_CHECKS_DEFERRED', message: 'checks deferred', severity: 'warning', source: 'runtime' }], checked_at: '2026-06-14T00:00:00Z' };
    const html = renderLabDetail({ lab, eligibility: elig });
    assert.ok(html.includes('deferred'), 'Missing deferred warning');
});

test('lab detail: 404 does not reveal unpublished details', () => {
    // renderLabDetail receives the published lab data only — 404 is handled at page level
    // Verify the renderer doesn't include any 'unpublished' leakage
    const html = renderNotFound('Lab');
    assert.ok(!html.includes('unpublished'), 'Must not reveal unpublished state');
    assert.ok(html.includes('not found'));
});

// ── renderSessionView ─────────────────────────────────────────────────────────
//
// Mock snapshots match the backend LearnerSessionSnapshot model exactly:
//   session_state (not state), title (not lab_title),
//   runtime_summary.ready_to_complete (not top-level ready_to_complete),
//   runtime_summary.failure_reason (not top-level failure_reason),
//   action_availability.can_check_current_step (not can_check_step),
//   step.status === 'passed' (not completed_step_ids),
//   step.is_current (not step_id === current_step_id),
//   step.check_summary (not last_verify_results at snapshot level).

function makeStep(stepId, title, { status = 'locked', isCurrent = false, checkSummary = null } = {}) {
    return { step_id: stepId, title, learner_goal: '', status, is_current: isCurrent, check_summary: checkSummary };
}

const ACTIVE_SNAPSHOT = {
    session_id: 'sess-abc',
    lab_id: 'lab-xyz',
    session_state: 'LAB_ACTIVE',
    title: 'Pod Networking',
    current_step_id: 'step-1',
    steps: [
        makeStep('step-1', 'Create a pod', { status: 'available', isCurrent: true }),
        makeStep('step-2', 'Check connectivity'),
    ],
    runtime_summary: { ready_to_complete: false, failure_reason: null, vm_status: 'active', cleanup_status: null, tainted: false },
    action_availability: { can_check_current_step: true, can_complete: false, can_abort: true, disabled_reasons: [] },
    issues: [],
    checked_at: '2026-06-14T00:00:00Z',
};

test('session view: active session shows current step', () => {
    const html = renderSessionView(ACTIVE_SNAPSHOT);
    assert.ok(html.includes('Create a pod'), 'Current step title missing');
    assert.ok(html.includes('Check connectivity'), 'Second step title missing');
    assert.ok(html.includes('data-step-status="current"'), 'Current step marker missing');
});

test('session view: session_state field used for status badge (not state)', () => {
    const html = renderSessionView(ACTIVE_SNAPSHOT);
    assert.ok(html.includes('LAB_ACTIVE'), 'session_state value not rendered in badge');
    assert.ok(!html.includes('UNKNOWN'), 'UNKNOWN badge must not appear when session_state is set');
});

test('session view: title field used for lab title (not lab_title)', () => {
    const html = renderSessionView(ACTIVE_SNAPSHOT);
    assert.ok(html.includes('Pod Networking'), 'title field not rendered');
    // Snapshot with no title should show nothing (not break)
    const noTitle = { ...ACTIVE_SNAPSHOT, title: '' };
    const html2 = renderSessionView(noTitle);
    assert.ok(!html2.includes('undefined'), 'undefined must not appear when title empty');
});

test('session view: action_availability.can_check_current_step controls Check button', () => {
    const html = renderSessionView(ACTIVE_SNAPSHOT);
    assert.ok(!hasDisabled(html, 'check-step'), 'Check step should be enabled (can_check_current_step=true)');
    assert.ok(hasDisabled(html, 'complete'), 'Complete must be disabled (can_complete=false)');
    assert.ok(!hasDisabled(html, 'abort'), 'Abort should be enabled (can_abort=true)');
});

test('session view: can_check_current_step=false disables Check button', () => {
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        action_availability: { ...ACTIVE_SNAPSHOT.action_availability, can_check_current_step: false },
    };
    const html = renderSessionView(snapshot);
    assert.ok(hasDisabled(html, 'check-step'), 'Check button must be disabled when can_check_current_step=false');
});

test('session view: runtime_summary.ready_to_complete controls data-ready and Complete button', () => {
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        runtime_summary: { ...ACTIVE_SNAPSHOT.runtime_summary, ready_to_complete: true },
        action_availability: { can_check_current_step: false, can_complete: true, can_abort: false, disabled_reasons: [] },
    };
    const html = renderSessionView(snapshot);
    assert.ok(hasAttr(html, 'data-ready', 'true'), 'Missing data-ready=true');
    assert.ok(!hasDisabled(html, 'complete'), 'Complete should be enabled when ready_to_complete=true');
});

test('session view: step.status=passed marks step as passed (not completed_step_ids)', () => {
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        steps: [
            makeStep('step-1', 'Create a pod', { status: 'passed', isCurrent: false }),
            makeStep('step-2', 'Check connectivity', { status: 'available', isCurrent: true }),
        ],
        current_step_id: 'step-2',
    };
    const html = renderSessionView(snapshot);
    assert.ok(html.includes('data-step-status="passed"'), 'Passed step (status=passed) not marked');
    assert.ok(html.includes('data-step-status="current"'), 'Current step not marked');
});

test('session view: step.is_current marks current step', () => {
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        steps: [
            makeStep('step-1', 'Create a pod', { status: 'available', isCurrent: true }),
            makeStep('step-2', 'Check connectivity', { status: 'locked', isCurrent: false }),
        ],
    };
    const html = renderSessionView(snapshot);
    assert.ok(html.includes('data-step-status="current"'), 'is_current=true step not marked as current');
    assert.ok(html.includes('data-step-status="pending"'), 'locked step not marked as pending');
});

test('session view: step.check_summary rendered under current step (not snapshot.last_verify_results)', () => {
    const summary = { last_result: 'passed', safe_message: null, failure_reason: null };
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        steps: [makeStep('step-1', 'Create a pod', { status: 'available', isCurrent: true, checkSummary: summary })],
    };
    const html = renderSessionView(snapshot);
    assert.ok(html.includes('✓'), 'passed check icon missing');
    assert.ok(html.includes('passed'), 'passed label missing');
});

test('session view: check_summary passed with safe_message shows deployment detail', () => {
    const detail = 'Deployment "hello-deployment" is available with 1 ready replica in your isolated namespace. Kubernetes has created a Pod for this workload.';
    const summary = { last_result: 'passed', safe_message: detail, failure_reason: null };
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        steps: [makeStep('step-1', 'Create a deployment', { status: 'available', isCurrent: true, checkSummary: summary })],
    };
    const html = renderSessionView(snapshot);
    assert.ok(html.includes('✓'), 'passed icon missing');
    assert.ok(html.includes('1 ready replica'), 'deployment detail not shown for passed step');
    assert.ok(html.includes('Pod'), 'Pod mention missing from passed detail');
});

test('session view: check_summary failure shows error icon and failure_reason', () => {
    const summary = { last_result: 'failed', safe_message: null, failure_reason: 'namespace_not_found' };
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        steps: [makeStep('step-1', 'Create a pod', { status: 'available', isCurrent: true, checkSummary: summary })],
    };
    const html = renderSessionView(snapshot);
    assert.ok(html.includes('✗'), 'fail icon missing');
    assert.ok(html.includes('namespace_not_found'), 'failure_reason not shown');
});

test('session view: runtime_summary.failure_reason shown as banner (not snapshot.failure_reason)', () => {
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        runtime_summary: { ...ACTIVE_SNAPSHOT.runtime_summary, failure_reason: 'namespace_cleanup_failed' },
    };
    const html = renderSessionView(snapshot);
    assert.ok(html.includes('namespace_cleanup_failed'), 'failure_reason banner not shown');
});

test('session view: complete/abort disabled after terminal state', () => {
    const closed = {
        ...ACTIVE_SNAPSHOT,
        session_state: 'LAB_CLOSED',
        action_availability: { can_check_current_step: false, can_complete: false, can_abort: false, disabled_reasons: [] },
    };
    const html = renderSessionView(closed);
    assert.ok(hasDisabled(html, 'check-step'), 'Check step must be disabled in closed state');
    assert.ok(hasDisabled(html, 'complete'), 'Complete must be disabled in closed state');
    assert.ok(hasDisabled(html, 'abort'), 'Abort must be disabled in closed state');
});

test('session view: does not expose kubeconfig or vm_id', () => {
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        kubeconfig: 'apiVersion: v1\nclusters: ...',
        vm_id: '512',
        verifier_credential: 'eyJsometoken',
    };
    const html = renderSessionView(snapshot);
    assert.ok(!html.includes('apiVersion: v1'), 'kubeconfig must not appear');
    assert.ok(!html.includes('vm_id'), 'vm_id field must not appear');
});

// ── Safety: injected sensitive values must not render ─────────────────────────

test('E2E safety: injected token in mock response does not appear in rendered admin view', () => {
    const INJECTED_TOKEN = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.fake_sig_here_abcdef1234';
    const INJECTED_SECRET = 'super_secret_value_12345678901234567890123456789012345';
    const INJECTED_TRACEBACK = 'Traceback (most recent call last):\n  File "x.py" line 1';

    const preview = {
        ...PREVIEW,
        raw_model_output: INJECTED_TOKEN,
        provider_metadata: INJECTED_SECRET,
        hidden_prompt: INJECTED_TRACEBACK,
    };
    const html = renderAdminDraftView({ preview, decision: ALLOWED_DECISION });
    assertNoSensitiveDisplayData(html, [INJECTED_TOKEN, INJECTED_SECRET]);
});

test('E2E safety: injected secret in catalog item does not render', () => {
    const INJECTED = 'private_key_abc1234567890123456789012345678901234567890';
    const labs = [{ lab_id: 'x', title: 'Test', internal_secret: INJECTED }];
    const html = renderLabCatalog(labs);
    assertNoSensitiveDisplayData(html, [INJECTED]);
});

test('E2E safety: injected token in session snapshot does not render', () => {
    const INJECTED_TOKEN = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ2ZXJpZmllciJ9.fake_sig_padding_here';
    const snapshot = {
        ...ACTIVE_SNAPSHOT,
        verifier_credential: INJECTED_TOKEN,
        kubeconfig: 'apiVersion: v1\nclusters:\n- cluster:\n    server: https://k3s-api-server:6443',
    };
    const html = renderSessionView(snapshot);
    assertNoSensitiveDisplayData(html, [INJECTED_TOKEN]);
    assert.ok(!html.includes('apiVersion'), 'kubeconfig content must not leak');
});

// ── renderContractPackSummary ─────────────────────────────────────────────────

test('contract pack summary: renders version and endpoint count', () => {
    const pack = {
        version: '0.1',
        endpoints: [
            { method: 'GET', path: '/api/labs', response_model: 'list[LearnerLabCatalogItem]' },
            { method: 'POST', path: '/api/lab-sessions', response_model: 'LabSessionState' },
        ],
    };
    const html = renderContractPackSummary(pack);
    assert.ok(html.includes('v0.1'), 'Version not shown');
    assert.ok(html.includes('/api/labs'), 'Endpoint path not shown');
    assert.ok(html.includes('LearnerLabCatalogItem'), 'Response model not shown');
});

test('contract pack summary: null returns error state', () => {
    const html = renderContractPackSummary(null);
    assert.ok(html.includes('Failed to load'), 'Error state missing');
});

// ── renderNotFound ────────────────────────────────────────────────────────────

test('renderNotFound: does not include "unpublished"', () => {
    const html = renderNotFound('Lab');
    assert.ok(!html.includes('unpublished'), 'Must not reveal unpublished state');
});
