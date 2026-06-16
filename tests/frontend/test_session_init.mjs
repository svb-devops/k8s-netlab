/**
 * Tests for frontend/js/labgen-session-state.js — isSessionActive()
 * Run with: node --test tests/frontend/test_session_init.mjs
 *
 * Regression: the /snapshot endpoint returns LearnerSessionSnapshot, whose
 * status field is `session_state` (see backend/labgen/learner_session_snapshot.py).
 * labgen-session-init.js's syncTerminal() used to check `snapshot.lab_session_status`
 * instead — a field that only exists on the raw LabSessionState model, not on this
 * snapshot — so isActive was always false and the kubectl terminal panel never
 * appeared for real learners using the actual session page, even while LAB_ACTIVE.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';

const __dir = dirname(fileURLToPath(import.meta.url));
const { isSessionActive } =
    await import(resolve(__dir, '../../frontend/js/labgen-session-state.js'));

test('isSessionActive is true when snapshot.session_state is LAB_ACTIVE', () => {
    assert.equal(isSessionActive({ session_state: 'LAB_ACTIVE' }), true);
});

test('isSessionActive is false for other session_state values', () => {
    assert.equal(isSessionActive({ session_state: 'LAB_CLOSED' }), false);
    assert.equal(isSessionActive({ session_state: 'LAB_CREATED' }), false);
});

test('isSessionActive is false when snapshot has no session_state (regression: stale lab_session_status field)', () => {
    // This is the actual snapshot shape returned by GET /api/lab-sessions/:id/snapshot —
    // it never had a `lab_session_status` field, only `session_state`.
    assert.equal(isSessionActive({ lab_session_status: 'LAB_ACTIVE' }), false);
});

test('isSessionActive handles null/undefined snapshot', () => {
    assert.equal(isSessionActive(null), false);
    assert.equal(isSessionActive(undefined), false);
});
