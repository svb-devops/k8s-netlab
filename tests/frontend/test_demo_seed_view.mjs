/**
 * Tests for demo seed frontend:
 *   - renderDemoSeedResult (labgenViews.js)
 *   - seedDemoData method (labgenClient.js)
 *
 * Run with: node --test tests/frontend/test_demo_seed_view.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));
const {
    renderDemoSeedResult,
    renderErrorState,
} = await import(resolve(__dir, '../../frontend/js/labgenViews.js'));

const { assertNoSensitiveDisplayData } =
    await import(resolve(__dir, '../../frontend/js/labgenSecurity.js'));

const { LabGenClient, LabGenApiError, PATHS } =
    await import(resolve(__dir, '../../frontend/js/labgenClient.js'));

// ── Fixtures ──────────────────────────────────────────────────────────────────

const DEMO_RESULT = {
    seeded_scenarios: [
        'PYTHON_BASICS_PUBLISHED',
        'HTTP_API_BASICS_PUBLISHED',
        'DATA_TRANSFORM_REVIEW_BLOCKED',
        'RUNTIME_ACTIVE_SESSION',
        'RUNTIME_READY_TO_COMPLETE_SESSION',
        'RUNTIME_CLEANUP_FAILED_TAINTED_SESSION',
    ],
    created_or_updated_draft_ids: [
        'demo-python-basics-v1',
        'demo-http-api-basics-v1',
        'demo-data-transform-blocked-v1',
    ],
    created_or_updated_lab_ids: [
        'demo-python-basics-v1',
        'demo-http-api-basics-v1',
    ],
    created_or_updated_session_ids: [
        'demo-session-active-v1',
        'demo-session-ready-v1',
        'demo-session-cleanup-failed-v1',
    ],
    warnings: [],
    next_steps: [
        { label: 'Admin draft review: demo-python-basics-v1', path: '/labgen-admin.html?draftId=demo-python-basics-v1' },
        { label: 'Learner catalog (all published labs)',       path: '/labgen-catalog.html' },
        { label: 'Learner lab detail: demo-python-basics-v1', path: '/labgen-lab.html?labId=demo-python-basics-v1' },
        { label: 'Learner session snapshot: demo-session-active-v1', path: '/labgen-session.html?sessionId=demo-session-active-v1' },
    ],
};

const RESULT_WITH_WARNINGS = {
    ...DEMO_RESULT,
    warnings: ['PYTHON_BASICS draft did not reach PUBLISHED: draft'],
};

// ── renderDemoSeedResult ──────────────────────────────────────────────────────

test('renderDemoSeedResult - renders all 6 scenario names', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    for (const scenario of DEMO_RESULT.seeded_scenarios) {
        assert.ok(html.includes(scenario), `Missing scenario: ${scenario}`);
    }
});

test('renderDemoSeedResult - renders draft IDs as links to admin review', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('demo-python-basics-v1'));
    assert.ok(html.includes('/labgen-admin.html?draftId=demo-python-basics-v1'));
});

test('renderDemoSeedResult - renders published lab IDs as links to lab detail', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('/labgen-lab.html?labId=demo-python-basics-v1'));
    assert.ok(html.includes('/labgen-lab.html?labId=demo-http-api-basics-v1'));
});

test('renderDemoSeedResult - renders session IDs as links to session snapshot', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('/labgen-session.html?sessionId=demo-session-active-v1'));
});

test('renderDemoSeedResult - renders next_steps as anchor links', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('/labgen-catalog.html'), 'Missing catalog link');
    for (const step of DEMO_RESULT.next_steps) {
        assert.ok(html.includes(step.path), `Missing next_step path: ${step.path}`);
    }
});

test('renderDemoSeedResult - does not render warnings when none', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(!html.includes('Warnings'), 'Should not show Warnings section when empty');
});

test('renderDemoSeedResult - renders warnings when present', () => {
    const html = renderDemoSeedResult(RESULT_WITH_WARNINGS);
    assert.ok(html.includes('Warnings'), 'Should show Warnings section');
    assert.ok(html.includes('did not reach PUBLISHED'));
});

test('renderDemoSeedResult - passes assertNoSensitiveDisplayData', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.doesNotThrow(() => assertNoSensitiveDisplayData(html, []));
});

test('renderDemoSeedResult - does not render raw_model_output', () => {
    const resultWithRawOutput = {
        ...DEMO_RESULT,
        warnings: ['raw_model_output: {"key": "value"}'],
    };
    const html = renderDemoSeedResult(resultWithRawOutput);
    // The text is rendered escaped — check it doesn't appear as a key
    assert.ok(!html.includes('"raw_model_output"'), 'Must not render raw_model_output as JSON key');
});

test('renderDemoSeedResult - does not render secret/token values', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    // No sensitive values in the demo result fixture
    assert.ok(!html.includes('-----BEGIN'));
    assert.ok(!html.includes('client-key-data'));
});

test('renderDemoSeedResult - handles null gracefully', () => {
    const html = renderDemoSeedResult(null);
    assert.ok(html.includes('No seed result') || html.includes('Unable to load'));
});

test('renderDemoSeedResult - handles empty result gracefully', () => {
    const html = renderDemoSeedResult({
        seeded_scenarios: [],
        created_or_updated_draft_ids: [],
        created_or_updated_lab_ids: [],
        created_or_updated_session_ids: [],
        warnings: [],
        next_steps: [],
    });
    assert.ok(typeof html === 'string' && html.length > 0);
    assert.doesNotThrow(() => assertNoSensitiveDisplayData(html, []));
});

// ── labgenClient.seedDemoData ─────────────────────────────────────────────────

test('seedDemoData - PATHS.demoSeed is defined', () => {
    assert.ok(PATHS.demoSeed, 'PATHS.demoSeed must be defined');
    assert.ok(PATHS.demoSeed.includes('/demo/seed'), 'demoSeed path must include /demo/seed');
});

test('seedDemoData - calls POST /api/labgen/demo/seed', async () => {
    let capturedMethod, capturedUrl, capturedBody;
    const mockFetch = async (url, opts) => {
        capturedMethod = opts.method;
        capturedUrl = url;
        capturedBody = JSON.parse(opts.body);
        return {
            ok: true,
            json: async () => ({ ...DEMO_RESULT }),
        };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.seedDemoData({ reset: false, include_runtime_sessions: true });
    assert.equal(capturedMethod, 'POST');
    assert.ok(capturedUrl.includes('/api/labgen/demo/seed'));
    assert.equal(capturedBody.reset, false);
    assert.equal(capturedBody.include_runtime_sessions, true);
});

test('seedDemoData - sends scenarios when specified', async () => {
    let capturedBody;
    const mockFetch = async (url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return {
            ok: true,
            json: async () => ({ ...DEMO_RESULT, seeded_scenarios: ['PYTHON_BASICS_PUBLISHED'] }),
        };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.seedDemoData({ scenarios: ['PYTHON_BASICS_PUBLISHED'] });
    assert.deepEqual(capturedBody.scenarios, ['PYTHON_BASICS_PUBLISHED']);
});

test('seedDemoData - omits scenarios when not specified', async () => {
    let capturedBody;
    const mockFetch = async (url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return {
            ok: true,
            json: async () => ({ ...DEMO_RESULT }),
        };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.seedDemoData();
    assert.ok(!('scenarios' in capturedBody), 'scenarios should not be sent when not specified');
});

test('seedDemoData - throws LabGenApiError on 403', async () => {
    const mockFetch = async () => ({
        ok: false,
        status: 403,
        json: async () => ({ detail: 'Admin access required for LabGen draft management' }),
    });
    const client = new LabGenClient({ fetchFn: mockFetch });
    await assert.rejects(
        () => client.seedDemoData(),
        (err) => {
            assert.ok(err instanceof LabGenApiError);
            assert.equal(err.status, 403);
            return true;
        }
    );
});

test('seedDemoData - throws LabGenApiError on 401', async () => {
    const mockFetch = async () => ({
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
    });
    const client = new LabGenClient({ fetchFn: mockFetch });
    await assert.rejects(
        () => client.seedDemoData(),
        (err) => err instanceof LabGenApiError && err.status === 401
    );
});

test('seedDemoData - reset=true sends correct body', async () => {
    let capturedBody;
    const mockFetch = async (url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return {
            ok: true,
            json: async () => ({ ...DEMO_RESULT }),
        };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.seedDemoData({ reset: true });
    assert.equal(capturedBody.reset, true);
});

// ── Frontend dev page invariants (structural) ─────────────────────────────────

test('next_steps links use safe href (no inline handlers)', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    // No onclick or other inline event handlers in rendered links
    assert.ok(!html.includes('onclick='), 'Must not use onclick inline handlers');
    assert.ok(!html.includes('javascript:'), 'Must not use javascript: URIs');
});

test('next_steps admin path goes to labgen-admin.html', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('/labgen-admin.html'), 'Admin review path missing');
});

test('next_steps catalog path goes to labgen-catalog.html', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('/labgen-catalog.html'), 'Catalog path missing');
});

test('next_steps lab detail path goes to labgen-lab.html', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('/labgen-lab.html'), 'Lab detail path missing');
});

test('next_steps session path goes to labgen-session.html', () => {
    const html = renderDemoSeedResult(DEMO_RESULT);
    assert.ok(html.includes('/labgen-session.html'), 'Session snapshot path missing');
});

test('next_steps rejects javascript: URI — renders # instead', () => {
    const resultWithJsUri = {
        ...DEMO_RESULT,
        next_steps: [
            { label: 'Evil link', path: 'javascript:alert(1)' },
            { label: 'Safe link', path: '/labgen-catalog.html' },
        ],
    };
    const html = renderDemoSeedResult(resultWithJsUri);
    assert.ok(!html.includes('javascript:alert'), 'Must not render javascript: URI as href');
    assert.ok(html.includes('href="#"') || html.includes("href='#'"), 'Blocked path should render as #');
});

test('next_steps rejects non-root-relative paths', () => {
    const result = {
        ...DEMO_RESULT,
        next_steps: [{ label: 'External', path: 'https://evil.example.com' }],
    };
    const html = renderDemoSeedResult(result);
    assert.ok(!html.includes('https://evil.example.com'), 'Non-root-relative path must not be rendered as href');
});
