/**
 * LabGen Frontend Security Helpers
 *
 * sanitizeDisplayText  — call on every dynamic string before innerHTML insertion.
 * assertNoSensitiveDisplayData — TEST-ONLY; throws if rendered HTML leaks known-sensitive values.
 */

// Matches JWT tokens (three base64url segments)
const _JWT_RE = /eyJ[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+/g;

// Matches ≥60-char base64 blobs (kubeconfig data, long tokens)
const _LONG_BASE64_RE = /[A-Za-z0-9+/]{60,}={0,2}/g;

// Matches Bearer scheme tokens
const _BEARER_RE = /(?:Bearer|bearer)\s+[A-Za-z0-9._=+/\-]{8,}/g;

// Absolute keyword blocklist — values containing these must never reach the DOM.
// These are checked against leaf string VALUES, not JSON field names.
const _ABSOLUTE_VALUE_KEYWORDS = [
    'kubeconfig',
    'private_key',
    'Traceback (most recent call last)',
    'raw_model_output',
    'hidden_prompt',
    'provider_metadata',
];

/**
 * Redact known sensitive patterns from a display string.
 * Returns the sanitized string. Non-string values are returned unchanged.
 */
export function sanitizeDisplayText(text) {
    if (typeof text !== 'string') return text;
    let out = text
        .replace(_JWT_RE, '[REDACTED]')
        .replace(_LONG_BASE64_RE, '[REDACTED]')
        .replace(_BEARER_RE, 'Bearer [REDACTED]');
    return out;
}

/**
 * Escape HTML special characters. Use before inserting user-controlled text as text content.
 */
export function escapeHtml(text) {
    if (typeof text !== 'string') return String(text ?? '');
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * TEST-ONLY helper — throws if `html` (rendered output) contains:
 *   - any value from `knownSensitiveValues`
 *   - any JWT / long-base64 / Bearer pattern
 *   - any absolute keyword from _ABSOLUTE_VALUE_KEYWORDS
 *
 * @param {string} html - rendered HTML or display text to inspect
 * @param {string[]} knownSensitiveValues - injected sentinel values that must not appear
 */
export function assertNoSensitiveDisplayData(html, knownSensitiveValues = []) {
    if (typeof html !== 'string') {
        throw new TypeError('assertNoSensitiveDisplayData expects a string');
    }

    for (const val of knownSensitiveValues) {
        if (val && html.includes(val)) {
            throw new Error(
                `Sensitive injected value leaked into display: "${val.slice(0, 40)}..."`
            );
        }
    }

    // Reset lastIndex before exec
    _JWT_RE.lastIndex = 0;
    if (_JWT_RE.test(html)) {
        throw new Error('JWT token pattern leaked into display output');
    }

    _LONG_BASE64_RE.lastIndex = 0;
    if (_LONG_BASE64_RE.test(html)) {
        throw new Error('Long base64 blob leaked into display output');
    }

    for (const kw of _ABSOLUTE_VALUE_KEYWORDS) {
        if (html.includes(kw)) {
            throw new Error(`Absolute sensitive keyword "${kw}" leaked into display output`);
        }
    }
}
