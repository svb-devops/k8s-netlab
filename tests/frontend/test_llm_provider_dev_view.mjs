/**
 * Tests for LLM Provider Boundary frontend:
 *   - renderLLMProviderStatus (labgenViews.js)
 *   - getLLMProviderStatus / runProviderDryRun (labgenClient.js)
 *
 * Run with: node --test tests/frontend/test_llm_provider_dev_view.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));
const {
    renderLLMProviderStatus,
    renderErrorState,
} = await import(resolve(__dir, '../../frontend/js/labgenViews.js'));

const { assertNoSensitiveDisplayData } =
    await import(resolve(__dir, '../../frontend/js/labgenSecurity.js'));

const { LabGenClient, LabGenApiError, PATHS } =
    await import(resolve(__dir, '../../frontend/js/labgenClient.js'));

// ── Fixtures ──────────────────────────────────────────────────────────────────

const STATUS_FAKE_ONLY = {
    provider_name: 'fake',
    mode: 'fake_only',
    live_enabled: false,
    dry_run_available: false,
    timeout_ms: 30000,
    max_output_tokens: 4096,
    safety_policy_summary:
        'Prohibited: raw output, chain of thought, hidden prompts, provider data, API keys. ' +
        'sanitize_text() applied to all dynamic content.',
    warnings: [],
};

const STATUS_DRY_RUN = {
    ...STATUS_FAKE_ONLY,
    mode: 'dry_run',
    dry_run_available: true,
    warnings: [],
};

const STATUS_DISABLED = {
    ...STATUS_FAKE_ONLY,
    mode: 'disabled',
    warnings: ['LLM provider mode is disabled — generation uses fake/template path.'],
};

const DRY_RUN_RESP_VALID = {
    provider_name: 'fake',
    mode: 'dry_run',
    candidate_json: { title: 'Lab', steps: [] },
    warnings: ['dry-run: deterministic candidate — not a real LLM output'],
    usage_summary: 'dry-run (no provider calls)',
    rejected_reason: null,
};

const DRY_RUN_RESP_DISABLED = {
    provider_name: 'fake',
    mode: 'disabled',
    candidate_json: null,
    warnings: [],
    usage_summary: null,
    rejected_reason: 'provider_disabled',
};

// ── renderLLMProviderStatus ───────────────────────────────────────────────────

test('renderLLMProviderStatus - renders provider name', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(html.includes('fake'), 'Should render provider_name "fake"');
});

test('renderLLMProviderStatus - renders mode badge FAKE_ONLY', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(html.includes('FAKE_ONLY'), 'Should render mode badge');
});

test('renderLLMProviderStatus - renders mode badge DRY_RUN', () => {
    const html = renderLLMProviderStatus(STATUS_DRY_RUN);
    assert.ok(html.includes('DRY_RUN'), 'Should render DRY_RUN mode badge');
});

test('renderLLMProviderStatus - renders live_enabled false', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(html.includes('false'), 'Should render live_enabled=false');
});

test('renderLLMProviderStatus - renders timeout_ms', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(html.includes('30000'), 'Should render timeout_ms');
});

test('renderLLMProviderStatus - renders max_output_tokens', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(html.includes('4096'), 'Should render max_output_tokens');
});

test('renderLLMProviderStatus - renders safety_policy_summary', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(
        html.includes('Prohibited'),
        'Should render safety_policy_summary'
    );
});

test('renderLLMProviderStatus - dry_run available badge rendered', () => {
    const html = renderLLMProviderStatus(STATUS_DRY_RUN);
    assert.ok(html.includes('available'), 'Should show dry-run available badge');
});

test('renderLLMProviderStatus - warnings rendered when present', () => {
    const html = renderLLMProviderStatus(STATUS_DISABLED);
    assert.ok(
        html.includes('disabled'),
        'Should render warning text for disabled mode'
    );
});

test('renderLLMProviderStatus - no warnings section when empty', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    // Should not render a warning container for empty warnings
    assert.ok(!html.includes('text-yellow-700'), 'Should not render warning list for empty warnings');
});

test('renderLLMProviderStatus - does not render API keys', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(!html.includes('sk-'), 'Must not render any API key patterns');
    assert.ok(!html.match(/eyJ[A-Za-z0-9._-]+/), 'Must not render JWT-like strings');
});

test('renderLLMProviderStatus - does not render raw_model_output keyword in output', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(!html.includes('raw_model_output'), 'Must not render raw output keywords in HTML');
});

test('renderLLMProviderStatus - does not render hidden_prompt keyword in output', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    assert.ok(!html.includes('hidden_prompt'), 'Must not render hidden_prompt in HTML');
});

test('renderLLMProviderStatus - assertNoSensitiveDisplayData passes', () => {
    const html = renderLLMProviderStatus(STATUS_FAKE_ONLY);
    // Should not throw
    assert.doesNotThrow(() => assertNoSensitiveDisplayData(html));
});

test('renderLLMProviderStatus - null input returns error state', () => {
    const html = renderLLMProviderStatus(null);
    assert.ok(html.includes('Unable to load'), 'null should render error state');
});

test('renderLLMProviderStatus - missing input returns error state', () => {
    const html = renderLLMProviderStatus(undefined);
    assert.ok(html.includes('Unable to load'), 'undefined should render error state');
});

// ── labgenClient — getLLMProviderStatus ───────────────────────────────────────

test('PATHS has llmProviderStatus', () => {
    assert.ok('llmProviderStatus' in PATHS, 'PATHS must have llmProviderStatus');
    assert.equal(PATHS.llmProviderStatus, '/api/labgen/llm-provider/status');
});

test('PATHS has llmProviderDryRun', () => {
    assert.ok('llmProviderDryRun' in PATHS, 'PATHS must have llmProviderDryRun');
    assert.equal(PATHS.llmProviderDryRun, '/api/labgen/llm-provider/dry-run');
});

test('getLLMProviderStatus calls correct path', async () => {
    let capturedUrl = null;
    const mockFetch = async (url) => {
        capturedUrl = url;
        return { ok: true, json: async () => STATUS_FAKE_ONLY };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.getLLMProviderStatus();
    assert.equal(capturedUrl, '/api/labgen/llm-provider/status');
});

test('getLLMProviderStatus uses GET method', async () => {
    let capturedMethod = null;
    const mockFetch = async (url, opts) => {
        capturedMethod = opts.method;
        return { ok: true, json: async () => STATUS_FAKE_ONLY };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.getLLMProviderStatus();
    assert.equal(capturedMethod, 'GET');
});

test('runProviderDryRun calls correct path with POST', async () => {
    let capturedUrl = null;
    let capturedMethod = null;
    const mockFetch = async (url, opts) => {
        capturedUrl = url;
        capturedMethod = opts.method;
        return { ok: true, json: async () => DRY_RUN_RESP_VALID };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.runProviderDryRun({ sanitizedPrompt: 'test', injectMode: 'valid_candidate' });
    assert.equal(capturedUrl, '/api/labgen/llm-provider/dry-run');
    assert.equal(capturedMethod, 'POST');
});

test('runProviderDryRun sends inject_mode in body', async () => {
    let capturedBody = null;
    const mockFetch = async (url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return { ok: true, json: async () => DRY_RUN_RESP_VALID };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.runProviderDryRun({ sanitizedPrompt: 'my lab', injectMode: 'malformed' });
    assert.equal(capturedBody.inject_mode, 'malformed');
    assert.equal(capturedBody.sanitized_prompt, 'my lab');
});

test('runProviderDryRun defaults inject_mode to valid_candidate', async () => {
    let capturedBody = null;
    const mockFetch = async (url, opts) => {
        capturedBody = JSON.parse(opts.body);
        return { ok: true, json: async () => DRY_RUN_RESP_VALID };
    };
    const client = new LabGenClient({ fetchFn: mockFetch });
    await client.runProviderDryRun();
    assert.equal(capturedBody.inject_mode, 'valid_candidate');
});

test('runProviderDryRun handles rejected_reason response', async () => {
    const mockFetch = async () => ({
        ok: true,
        json: async () => DRY_RUN_RESP_DISABLED,
    });
    const client = new LabGenClient({ fetchFn: mockFetch });
    const resp = await client.runProviderDryRun();
    assert.equal(resp.rejected_reason, 'provider_disabled');
});

test('getLLMProviderStatus throws LabGenApiError on 403', async () => {
    const mockFetch = async () => ({
        ok: false,
        status: 403,
        json: async () => ({ detail: 'Admin access required for LabGen draft management' }),
    });
    const client = new LabGenClient({ fetchFn: mockFetch });
    await assert.rejects(
        () => client.getLLMProviderStatus(),
        (err) => err instanceof LabGenApiError && err.status === 403
    );
});

// ── Security: no sensitive data in dry-run display ────────────────────────────

test('renderLLMProviderStatus - assertNoSensitiveDisplayData for DRY_RUN status', () => {
    const html = renderLLMProviderStatus(STATUS_DRY_RUN);
    assert.doesNotThrow(() => assertNoSensitiveDisplayData(html));
});

test('renderLLMProviderStatus - assertNoSensitiveDisplayData for DISABLED status', () => {
    const html = renderLLMProviderStatus(STATUS_DISABLED);
    assert.doesNotThrow(() => assertNoSensitiveDisplayData(html));
});
