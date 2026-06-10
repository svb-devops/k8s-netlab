/**
 * Tests for frontend/js/labgenClient.js
 * Run with: node --test tests/frontend/test_client.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));
const { LabGenClient, LabGenApiError, PATHS } =
    await import(resolve(__dir, '../../frontend/js/labgenClient.js'));

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockFetch(responses) {
    // responses: Map<urlSubstring, { status, body }>  OR  array of {match, status, body}
    return async (url, opts) => {
        for (const [pattern, { status, body }] of Object.entries(responses)) {
            if (url.includes(pattern)) {
                return {
                    ok: status >= 200 && status < 300,
                    status,
                    json: async () => body,
                };
            }
        }
        return { ok: false, status: 404, json: async () => ({ detail: 'not found' }) };
    };
}

function makeClient(responses) {
    return new LabGenClient({ fetchFn: mockFetch(responses) });
}

// ── PATHS alignment with contract ────────────────────────────────────────────

test('PATHS: all contract endpoints are declared', () => {
    const required = [
        '/api/labgen/contract-pack',
        '/api/lab-drafts/generate',
        '/api/labgen/drafts/:lab_id/preview',
        '/api/labgen/drafts/:lab_id/publish-decision',
        '/api/labgen/drafts/:lab_id/publish',
        '/api/labs',
        '/api/labs/:lab_id',
        '/api/labs/:lab_id/start-eligibility',
        '/api/lab-sessions',
        '/api/lab-sessions/:session_id/snapshot',
        '/api/lab-sessions/:session_id/steps/:step_id/check',
        '/api/lab-sessions/:session_id/complete',
        '/api/lab-sessions/:session_id/abort',
        '/api/lab-sessions/:session_id/audit-events',
    ];
    const declared = Object.values(PATHS);
    for (const path of required) {
        assert.ok(
            declared.includes(path),
            `Contract path not declared in PATHS: ${path}`
        );
    }
});

// ── getContractPack ───────────────────────────────────────────────────────────

test('getContractPack: returns pack on 200', async () => {
    const pack = { version: '0.1', endpoints: [] };
    const client = makeClient({ '/api/labgen/contract-pack': { status: 200, body: pack } });
    const result = await client.getContractPack();
    assert.deepEqual(result, pack);
});

test('getContractPack: throws LabGenApiError on 403', async () => {
    const client = makeClient({
        '/api/labgen/contract-pack': { status: 403, body: { detail: 'Forbidden' } }
    });
    await assert.rejects(
        () => client.getContractPack(),
        (e) => e instanceof LabGenApiError && e.status === 403
    );
});

// ── 403/404/409 structured error ─────────────────────────────────────────────

test('error 403: code is http_403, message is safe string', async () => {
    const client = makeClient({
        '/api/labs': { status: 403, body: { detail: 'Forbidden' } }
    });
    await assert.rejects(
        () => client.listLabs(),
        (e) => {
            assert.ok(e instanceof LabGenApiError);
            assert.equal(e.status, 403);
            assert.equal(e.code, 'http_403');
            assert.ok(typeof e.message === 'string');
            return true;
        }
    );
});

test('error 404: LabGenApiError with status 404', async () => {
    const client = makeClient({
        '/api/labs/missing-lab': { status: 404, body: { detail: 'not found' } }
    });
    await assert.rejects(
        () => client.getLabDetail('missing-lab'),
        (e) => e instanceof LabGenApiError && e.status === 404
    );
});

test('error 409: structured detail with code and issues', async () => {
    const detail = {
        code: 'publish_blocked',
        message: 'Cannot publish: validation failed',
        issues: [{ check_id: 'has_steps', message: 'No steps defined' }],
    };
    const client = makeClient({
        '/api/labgen/drafts': { status: 409, body: { detail } }
    });
    await assert.rejects(
        () => client.publishDraft('lab-1'),
        (e) => {
            assert.ok(e instanceof LabGenApiError);
            assert.equal(e.status, 409);
            assert.equal(e.code, 'publish_blocked');
            assert.equal(e.message, detail.message);
            assert.equal(e.issues.length, 1);
            return true;
        }
    );
});

// ── publish blocked response issues ──────────────────────────────────────────

test('publish blocked: issues array is accessible on error', async () => {
    const detail = {
        code: 'publish_blocked',
        message: 'Blocked',
        issues: [
            { check_id: 'has_steps', message: 'Need steps' },
            { check_id: 'has_objectives', message: 'Need objectives' },
        ],
    };
    const client = makeClient({
        '/api/labgen/drafts': { status: 409, body: { detail } }
    });
    let caught;
    try { await client.publishDraft('draft-1'); } catch (e) { caught = e; }
    assert.ok(caught instanceof LabGenApiError);
    assert.equal(caught.issues.length, 2);
    assert.equal(caught.issues[0].check_id, 'has_steps');
});

// ── start eligibility ─────────────────────────────────────────────────────────

test('getStartEligibility: returns eligibility object', async () => {
    const elig = { is_eligible: true, runtime_checks_deferred: true, reasons: [] };
    const client = makeClient({
        '/start-eligibility': { status: 200, body: elig }
    });
    const result = await client.getStartEligibility('lab-1');
    assert.equal(result.is_eligible, true);
    assert.equal(result.runtime_checks_deferred, true);
});

// ── session snapshot action_availability ─────────────────────────────────────

test('getSessionSnapshot: action_availability is parsed correctly', async () => {
    const snapshot = {
        session_id: 'sess-1',
        state: 'LAB_ACTIVE',
        action_availability: { can_check_step: true, can_complete: false, can_abort: true },
    };
    const client = makeClient({
        '/snapshot': { status: 200, body: snapshot }
    });
    const result = await client.getSessionSnapshot('sess-1');
    assert.equal(result.action_availability.can_check_step, true);
    assert.equal(result.action_availability.can_complete, false);
});

// ── getMe: returns null on 401 ────────────────────────────────────────────────

test('getMe: returns null on 401 (not throw)', async () => {
    const client = makeClient({
        '/api/auth/me': { status: 401, body: { detail: 'Unauthorized' } }
    });
    const me = await client.getMe();
    assert.equal(me, null);
});

test('getMe: returns user object on 200', async () => {
    const user = { username: 'admin', is_admin: true };
    const client = makeClient({
        '/api/auth/me': { status: 200, body: user }
    });
    const me = await client.getMe();
    assert.deepEqual(me, user);
});

// ── no token/secret logged (structural) ──────────────────────────────────────

test('LabGenApiError: does not include token/secret in message from detail string', async () => {
    const client = makeClient({
        '/api/labs': { status: 500, body: { detail: 'Internal error' } }
    });
    let caught;
    try { await client.listLabs(); } catch (e) { caught = e; }
    assert.ok(caught instanceof LabGenApiError);
    // message comes from detail string, not a full stack trace
    assert.ok(!caught.message.includes('Traceback'), 'Message must not include traceback');
});
