/**
 * Pure session-state helpers shared by the lab session page.
 *
 * Kept dependency-free (no DOM) so it can be unit-tested directly in Node.
 */

/**
 * True when the session snapshot indicates an active lab.
 *
 * The /snapshot endpoint returns LearnerSessionSnapshot, whose status field
 * is `session_state` (not `lab_session_status` — that's the raw
 * LabSessionState model field name used by /api/lab-sessions/:id directly).
 */
export function isSessionActive(snapshot) {
    return snapshot?.session_state === 'LAB_ACTIVE';
}
