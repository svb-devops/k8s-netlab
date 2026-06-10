/**
 * LabGen API Client
 *
 * All paths are sourced from the contract pack (GET /api/labgen/contract-pack).
 * No endpoint is hard-coded independently — every path constant below must
 * match a corresponding entry in api_contract.py.
 *
 * Constructor accepts an optional `fetchFn` for test injection (default: globalThis.fetch).
 */

// Contract-sourced path templates — keep in sync with api_contract.py
const PATHS = {
    demoSeed:        '/api/labgen/demo/seed',
    contractPack:    '/api/labgen/contract-pack',
    generateDraft:   '/api/lab-drafts/generate',
    draftPreview:    '/api/labgen/drafts/:lab_id/preview',
    publishDecision: '/api/labgen/drafts/:lab_id/publish-decision',
    publishDraft:    '/api/labgen/drafts/:lab_id/publish',
    listLabs:        '/api/labs',
    labDetail:       '/api/labs/:lab_id',
    startEligibility:'/api/labs/:lab_id/start-eligibility',
    listSessions:    '/api/lab-sessions',
    sessionSnapshot: '/api/lab-sessions/:session_id/snapshot',
    startLab:        '/api/lab-sessions',
    checkStep:       '/api/lab-sessions/:session_id/steps/:step_id/check',
    completeSession: '/api/lab-sessions/:session_id/complete',
    abortSession:    '/api/lab-sessions/:session_id/abort',
    auditEvents:     '/api/lab-sessions/:session_id/audit-events',
    // auth helper — not in labgen contract, used for auth guard only
    authMe:          '/api/auth/me',
};

function _fill(template, params) {
    return Object.entries(params).reduce(
        (path, [k, v]) => path.replace(`:${k}`, encodeURIComponent(String(v))),
        template
    );
}

export class LabGenApiError extends Error {
    /**
     * @param {number} status
     * @param {string} code    - structured error code from backend detail.code
     * @param {string} message - human-readable summary (safe to display)
     * @param {object[]} issues - structured issues list (publish-blocked, eligibility checks, etc.)
     */
    constructor(status, code, message, issues = []) {
        super(message);
        this.name = 'LabGenApiError';
        this.status = status;
        this.code = code;
        this.issues = issues;
    }
}

export class LabGenClient {
    /**
     * @param {object} opts
     * @param {string}   [opts.baseURL=''] - prefix for all requests (empty = same-origin)
     * @param {Function} [opts.fetchFn]    - fetch implementation (default: globalThis.fetch)
     */
    constructor({ baseURL = '', fetchFn } = {}) {
        this._base = baseURL;
        this._fetch = fetchFn ?? ((...args) => globalThis.fetch(...args));
    }

    async _request(method, url, body) {
        const opts = {
            method,
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
        };
        if (body !== undefined) opts.body = JSON.stringify(body);

        const resp = await this._fetch(this._base + url, opts);
        let payload;
        try {
            payload = await resp.json();
        } catch {
            payload = null;
        }

        if (!resp.ok) {
            const detail = payload?.detail;
            const code    = (typeof detail === 'object' ? detail?.code   : null) ?? `http_${resp.status}`;
            const msg     = (typeof detail === 'object' ? detail?.message : typeof detail === 'string' ? detail : null)
                            ?? `Request failed (${resp.status})`;
            const issues  = (typeof detail === 'object' ? detail?.issues : null) ?? [];
            throw new LabGenApiError(resp.status, code, msg, issues);
        }

        return payload;
    }

    // ── Auth guard helper ─────────────────────────────────────────────────────
    /** Returns { username, is_admin } or null on 401/403 */
    async getMe() {
        try {
            return await this._request('GET', PATHS.authMe);
        } catch (e) {
            if (e instanceof LabGenApiError && (e.status === 401 || e.status === 403)) return null;
            throw e;
        }
    }

    // ── Contract pack ─────────────────────────────────────────────────────────
    async getContractPack() {
        return this._request('GET', PATHS.contractPack);
    }

    // ── Admin: draft generation & review ─────────────────────────────────────
    /** POST /api/lab-drafts/generate */
    async generateDraft(articleText, hints = {}) {
        return this._request('POST', PATHS.generateDraft, { article_text: articleText, ...hints });
    }

    /** GET /api/labgen/drafts/:lab_id/preview */
    async getDraftPreview(labId) {
        return this._request('GET', _fill(PATHS.draftPreview, { lab_id: labId }));
    }

    /** GET /api/labgen/drafts/:lab_id/publish-decision */
    async getPublishDecision(labId) {
        return this._request('GET', _fill(PATHS.publishDecision, { lab_id: labId }));
    }

    /** POST /api/labgen/drafts/:lab_id/publish */
    async publishDraft(labId) {
        return this._request('POST', _fill(PATHS.publishDraft, { lab_id: labId }));
    }

    // ── Learner: catalog & lab detail ─────────────────────────────────────────
    /** GET /api/labs */
    async listLabs() {
        return this._request('GET', PATHS.listLabs);
    }

    /** GET /api/labs/:lab_id */
    async getLabDetail(labId) {
        return this._request('GET', _fill(PATHS.labDetail, { lab_id: labId }));
    }

    /** GET /api/labs/:lab_id/start-eligibility */
    async getStartEligibility(labId) {
        return this._request('GET', _fill(PATHS.startEligibility, { lab_id: labId }));
    }

    // ── Learner: sessions ─────────────────────────────────────────────────────
    /** GET /api/lab-sessions */
    async listSessions() {
        return this._request('GET', PATHS.listSessions);
    }

    /** GET /api/lab-sessions/:session_id/snapshot */
    async getSessionSnapshot(sessionId) {
        return this._request('GET', _fill(PATHS.sessionSnapshot, { session_id: sessionId }));
    }

    /** POST /api/lab-sessions  { lab_id } */
    async startLab(labId) {
        return this._request('POST', PATHS.startLab, { lab_id: labId });
    }

    /** POST /api/lab-sessions/:session_id/steps/:step_id/check */
    async checkStep(sessionId, stepId) {
        return this._request('POST', _fill(PATHS.checkStep, { session_id: sessionId, step_id: stepId }));
    }

    /** POST /api/lab-sessions/:session_id/complete */
    async completeSession(sessionId) {
        return this._request('POST', _fill(PATHS.completeSession, { session_id: sessionId }));
    }

    /** POST /api/lab-sessions/:session_id/abort */
    async abortSession(sessionId) {
        return this._request('POST', _fill(PATHS.abortSession, { session_id: sessionId }));
    }

    /** GET /api/lab-sessions/:session_id/audit-events */
    async getAuditEvents(sessionId) {
        return this._request('GET', _fill(PATHS.auditEvents, { session_id: sessionId }));
    }

    // ── Demo seed (admin-only, dev/demo use only) ─────────────────────────────
    /**
     * POST /api/labgen/demo/seed
     * @param {object} opts
     * @param {string[]} [opts.scenarios] - scenario IDs to seed (default: all)
     * @param {boolean}  [opts.reset=false]
     * @param {boolean}  [opts.include_runtime_sessions=true]
     */
    async seedDemoData({ scenarios, reset = false, include_runtime_sessions = true } = {}) {
        const body = { reset, include_runtime_sessions };
        if (scenarios !== undefined) body.scenarios = scenarios;
        return this._request('POST', PATHS.demoSeed, body);
    }
}

// Singleton for browser use — tests instantiate their own client with a mock fetch
let _browserClient;
export function getBrowserClient() {
    if (!_browserClient) _browserClient = new LabGenClient();
    return _browserClient;
}

// Export path constants so tests can assert contract alignment
export { PATHS };
