/**
 * LabGen Pure View Renderers
 *
 * Every exported function is pure: it takes a plain data object and returns
 * an HTML string. No DOM side-effects, no module-level state.
 * This design allows node:test to import and assert on output without jsdom.
 *
 * All dynamic values are passed through escapeHtml / sanitizeDisplayText
 * before being embedded in HTML.
 */

import { escapeHtml, sanitizeDisplayText } from './labgenSecurity.js';

// ─── Shared primitives ────────────────────────────────────────────────────────

function _safe(v) {
    return escapeHtml(sanitizeDisplayText(String(v ?? '')));
}

function _badge(text, colorClass) {
    return `<span class="inline-block px-2 py-0.5 rounded text-xs font-medium ${colorClass}">${_safe(text)}</span>`;
}

function _statusBadge(status) {
    // Dark-theme chip colors: this badge is only ever rendered inside
    // renderSessionView, which is exclusive to the dark learner-flow pages
    // (labgen-session.html) — safe to hardcode dark palette here.
    const map = {
        LAB_ACTIVE:         'bg-green-500/15 text-green-400 border border-green-500/30',
        LAB_COMPLETED:      'bg-k8s-blue/15 text-blue-400 border border-blue-500/30',
        LAB_CLOSED:         'bg-devops-surface-2 text-devops-muted border border-devops-border-strong',
        LAB_ABORTED:        'bg-red-500/15 text-red-400 border border-red-500/30',
        LAB_CLEANUP_FAILED: 'bg-orange-500/15 text-orange-400 border border-orange-500/30',
        IMAGE_CHECK_RUNNING:'bg-amber-500/15 text-amber-400 border border-amber-500/30',
    };
    return _badge(status, map[status] ?? 'bg-devops-surface-2 text-devops-muted border border-devops-border-strong');
}

// ─── Error / empty states ─────────────────────────────────────────────────────
//
// theme defaults to 'light' so existing admin/dev callers (renderContractPackSummary,
// renderLLMProviderStatus, renderAdapterStatus, renderDemoSeedResult, renderAdminDraftView)
// keep their original rendered output unchanged. Only the learner-facing lab flow
// (catalog/lab/session init.js, and renderSessionView's internal call) passes 'dark'.

export function renderErrorState(message, theme = 'light') {
    const safeMsg = _safe(message);
    if (theme === 'dark') {
        return `<div class="p-6 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 font-plex">
            <p class="font-medium">Unable to load</p>
            <p class="text-sm mt-1 text-devops-muted">${safeMsg}</p>
        </div>`;
    }
    return `<div class="p-6 rounded-lg bg-red-50 border border-red-200 text-red-700">
        <p class="font-medium">Unable to load</p>
        <p class="text-sm mt-1">${safeMsg}</p>
    </div>`;
}

export function renderNotFound(entity = 'Resource', theme = 'light') {
    if (theme === 'dark') {
        return `<div class="p-6 rounded-lg bg-devops-surface border border-devops-border text-devops-muted text-center font-plex">
            <p class="font-medium">${_safe(entity)} not found</p>
        </div>`;
    }
    return `<div class="p-6 rounded-lg bg-gray-50 border border-gray-200 text-gray-600 text-center">
        <p class="font-medium">${_safe(entity)} not found</p>
    </div>`;
}

export function renderLoading(theme = 'light') {
    if (theme === 'dark') {
        return `<div class="flex items-center gap-2 text-devops-muted p-6 font-plex">
            <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
            </svg>
            <span>Loading…</span>
        </div>`;
    }
    return `<div class="flex items-center gap-2 text-gray-500 p-6">
        <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
        </svg>
        <span>Loading…</span>
    </div>`;
}

// ─── Admin: Draft Review ──────────────────────────────────────────────────────

/**
 * @param {object} p
 * @param {object} p.preview   - DraftPreviewSnapshot
 * @param {object} p.decision  - PublishDecision
 */
export function renderAdminDraftView({ preview, decision }) {
    const isAllowed   = decision?.status === 'ALLOWED';
    const isBlocked   = decision?.status === 'BLOCKED';
    const decBadge    = isAllowed
        ? _badge('ALLOWED', 'bg-green-100 text-green-800')
        : isBlocked
            ? _badge('BLOCKED', 'bg-red-100 text-red-700')
            : _badge(decision?.status ?? 'UNKNOWN', 'bg-gray-100 text-gray-600');

    const blockedIssues = isBlocked && Array.isArray(decision?.issues)
        ? decision.issues
            .filter(i => i?.severity === 'error')
            .map(i => `<li class="text-red-700 text-sm">${_safe(i?.message ?? i)}</li>`)
            .join('')
        : '';

    // Image readiness section (admin-only; never shows registry credentials)
    const ir = preview?.image_readiness;
    const irStatus = ir?.status ?? null;
    const irStatusClass = irStatus === 'READY'
        ? 'bg-green-100 text-green-800'
        : irStatus ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600';
    const irBadge = irStatus ? _badge(irStatus, irStatusClass) : '';
    const irIssues = Array.isArray(ir?.issues) && ir.issues.length > 0
        ? ir.issues.map(i => {
            const cls = i?.severity === 'error' ? 'text-red-700' : 'text-yellow-700';
            return `<li class="${cls} text-sm">[${_safe(i?.code ?? '')}] ${_safe(i?.message ?? '')}</li>`;
          }).join('')
        : '';
    const irCountSummary = ir ? [
        ir.resolved_image_count > 0 ? `${_safe(ir.resolved_image_count)} resolved` : null,
        ir.unresolved_image_count > 0 ? `${_safe(ir.unresolved_image_count)} unresolved` : null,
        ir.blocked_image_count > 0 ? `${_safe(ir.blocked_image_count)} blocked` : null,
        ir.missing_image_count > 0 ? `${_safe(ir.missing_image_count)} missing` : null,
    ].filter(Boolean).join(', ') : '';

    const validationIssues = Array.isArray(preview?.validation_issues)
        ? preview.validation_issues.map(i =>
            `<li class="text-yellow-700 text-sm">${_safe(i?.check_id ?? '')} — ${_safe(i?.message ?? i)}</li>`
          ).join('')
        : '';

    const objectives = Array.isArray(preview?.objectives)
        ? preview.objectives.map(o => `<li class="text-sm text-gray-700">${_safe(o)}</li>`).join('')
        : '';

    const steps = Array.isArray(preview?.steps)
        ? preview.steps.map((s, idx) => `
            <div class="border border-gray-200 rounded p-3 mb-2">
                <p class="font-medium text-sm">${_safe(idx + 1)}. ${_safe(s?.title ?? s?.step_id ?? '')}</p>
                ${s?.description ? `<p class="text-xs text-gray-500 mt-1">${_safe(s.description)}</p>` : ''}
            </div>`
          ).join('')
        : '';

    return `
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <h2 class="text-xl font-semibold text-gray-900">${_safe(preview?.title ?? 'Draft')}</h2>
            ${decBadge}
        </div>

        ${preview?.summary ? `<p class="text-gray-600">${_safe(preview.summary)}</p>` : ''}

        ${objectives ? `
        <div>
            <h3 class="font-medium text-gray-700 mb-2">Objectives</h3>
            <ul class="list-disc pl-5 space-y-1">${objectives}</ul>
        </div>` : ''}

        ${steps ? `
        <div>
            <h3 class="font-medium text-gray-700 mb-2">Steps</h3>
            ${steps}
        </div>` : ''}

        ${validationIssues ? `
        <div class="bg-yellow-50 border border-yellow-200 rounded p-4">
            <h3 class="font-medium text-yellow-800 mb-2">Validation Issues</h3>
            <ul class="list-disc pl-5 space-y-1">${validationIssues}</ul>
        </div>` : ''}

        ${irStatus ? `
        <div class="border border-gray-200 rounded p-4">
            <div class="flex items-center gap-2 mb-2">
                <h3 class="font-medium text-gray-700">Image Readiness</h3>
                ${irBadge}
            </div>
            ${irCountSummary ? `<p class="text-xs text-gray-500 mb-2">${irCountSummary}</p>` : ''}
            ${irIssues ? `<ul class="list-disc pl-5 space-y-1">${irIssues}</ul>` : ''}
        </div>` : ''}

        <div class="border-t pt-4">
            <h3 class="font-medium text-gray-700 mb-2">Publish Decision</h3>
            <div class="mb-3">${decBadge}</div>
            ${isBlocked && blockedIssues ? `
            <div class="bg-red-50 border border-red-200 rounded p-3 mb-4">
                <p class="text-sm font-medium text-red-700 mb-1">Blocked reasons:</p>
                <ul class="list-disc pl-5 space-y-1">${blockedIssues}</ul>
            </div>` : ''}
            <button
                data-action="publish"
                data-publish-enabled="${isAllowed}"
                ${!isAllowed ? 'disabled' : ''}
                class="px-4 py-2 rounded font-medium text-sm
                    ${isAllowed
                        ? 'bg-blue-600 text-white hover:bg-blue-700 cursor-pointer'
                        : 'bg-gray-200 text-gray-400 cursor-not-allowed'}">
                Publish Lab
            </button>
        </div>
    </div>`;
}

// ─── Learner: Lab Catalog ─────────────────────────────────────────────────────
//
// Labs are grouped into two domains (target_domain: "k8s" | "linux") and
// rendered as separate sections rather than one mixed flat grid — owner
// feedback was that lumping unrelated domains into a single grid with no
// hierarchy "毫无美感" (no aesthetic sense) and that Linux/K8s should read
// as distinct tracks if the product already treats them as such internally.
// Missing/unrecognized target_domain defaults to the "k8s" section so older
// catalog payloads (and existing tests that omit the field) keep rendering.

const _DOMAIN_META = {
    k8s: {
        label: 'Kubernetes',
        blurb: '容器编排故障排查与运维实战',
        accent: 'border-k8s-blue',
        chipBg: 'bg-k8s-blue/15 text-blue-400 border border-k8s-blue/30',
        icon: '<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>',
    },
    linux: {
        label: 'Linux',
        blurb: '文件系统与命令行基础操作',
        accent: 'border-amber-500',
        chipBg: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
        icon: '<path d="M4 4h16v16H4V4zm2.5 3.5l3 3-3 3M12 15h5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    },
};

function _labCard(lab, domainKey) {
    const meta = _DOMAIN_META[domainKey];
    const startable = lab?.is_startable === true;
    return `
    <a href="/labgen-lab.html?labId=${encodeURIComponent(lab?.lab_id ?? '')}"
       class="group block bg-devops-surface border border-devops-border border-t-2 ${meta.accent}
              rounded-lg p-5 hover:bg-devops-surface-2 hover:-translate-y-0.5
              transition-all duration-150 shadow-sm hover:shadow-lg hover:shadow-black/20">
        <div class="flex items-start justify-between gap-3">
            <h3 class="font-semibold text-devops-text leading-snug line-clamp-2">${_safe(lab?.title ?? 'Untitled')}</h3>
            ${startable
                ? _badge('Startable', 'bg-green-500/15 text-green-400 border border-green-500/30 shrink-0')
                : _badge('Not available', 'bg-devops-surface-2 text-devops-faint border border-devops-border-strong shrink-0')}
        </div>
        ${lab?.summary ? `<p class="text-sm text-devops-muted mt-2 leading-relaxed line-clamp-3">${_safe(lab.summary)}</p>` : ''}
        <div class="flex items-center justify-between mt-4 pt-3 border-t border-devops-border">
            <div class="flex gap-3 text-xs font-plex-mono text-devops-faint">
                ${lab?.objective_count != null ? `<span>${_safe(lab.objective_count)} objectives</span>` : ''}
                ${lab?.step_count != null ? `<span>${_safe(lab.step_count)} steps</span>` : ''}
            </div>
            <span class="text-xs font-plex-mono text-devops-faint group-hover:text-devops-text transition-colors">开始 →</span>
        </div>
    </a>`;
}

function _domainSection(domainKey, labs) {
    const meta = _DOMAIN_META[domainKey];
    return `
    <section>
        <div class="flex items-center gap-2.5 mb-1">
            <svg class="w-5 h-5 ${domainKey === 'linux' ? 'text-amber-500' : 'text-k8s-blue'}" fill="currentColor" viewBox="0 0 24 24">${meta.icon}</svg>
            <h2 class="text-lg font-bold text-devops-text">${meta.label}</h2>
            <span class="text-xs font-plex-mono text-devops-faint">${labs.length}</span>
        </div>
        <p class="text-sm text-devops-faint mb-4">${meta.blurb}</p>
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            ${labs.map(lab => _labCard(lab, domainKey)).join('')}
        </div>
    </section>`;
}

/**
 * @param {object[]} labs - LearnerLabCatalogItem[]
 */
export function renderLabCatalog(labs) {
    if (!Array.isArray(labs) || labs.length === 0) {
        return `<p class="text-devops-muted text-center py-12">No published labs available yet.</p>`;
    }

    const byDomain = { k8s: [], linux: [] };
    for (const lab of labs) {
        const key = lab?.target_domain === 'linux' ? 'linux' : 'k8s';
        byDomain[key].push(lab);
    }

    const sections = ['k8s', 'linux']
        .filter(key => byDomain[key].length > 0)
        .map(key => _domainSection(key, byDomain[key]))
        .join('<div class="h-px bg-devops-border my-8"></div>');

    return `<div class="flex flex-col gap-8 font-plex">${sections}</div>`;
}

// ─── Learner: Lab Detail ──────────────────────────────────────────────────────

/**
 * @param {object} p
 * @param {object} p.lab         - LearnerLabDetail
 * @param {object} p.eligibility - LearnerLabEligibility
 */
/**
 * title is always escaped internally (plain text only — never pass markup).
 * bodyHtml is NOT escaped: it's inserted as-is, so callers must pass either a
 * static string or HTML already built from _safe()-escaped pieces (matching
 * this file's file-level invariant that all dynamic values pass through
 * escapeHtml/sanitizeDisplayText before being embedded).
 */
function _alertBox({ icon, bg, border, text, title, bodyHtml }) {
    return `
    <div class="flex gap-3 ${bg} border ${border} rounded-lg p-4 font-plex">
        <svg class="w-5 h-5 flex-shrink-0 mt-0.5 ${text}" fill="currentColor" viewBox="0 0 20 20">${icon}</svg>
        <div class="min-w-0">
            <p class="text-sm font-semibold ${text}">${_safe(title)}</p>
            <p class="text-sm mt-0.5 ${text}">${bodyHtml}</p>
        </div>
    </div>`;
}

const _ICON_INFO = '<path fill-rule="evenodd" d="M18 10A8 8 0 11 2 10a8 8 0 0116 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9zm1-4a1 1 0 100 2 1 1 0 000-2z" clip-rule="evenodd"/>';
const _ICON_ERROR = '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>';
const _ICON_CHECK = '<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd"/>';

export function renderLabDetail({ lab, eligibility }) {
    const canStart  = eligibility?.is_startable === true;
    const deferred  = Array.isArray(eligibility?.issues) &&
        eligibility.issues.some(i => i?.code === 'RUNTIME_CHECKS_DEFERRED');

    const steps = Array.isArray(lab?.steps_preview) ? lab.steps_preview : [];

    const objectives = Array.isArray(lab?.objectives)
        ? lab.objectives.map(o => `
            <li class="flex items-start gap-2">
                <svg class="w-4 h-4 flex-shrink-0 mt-0.5 text-k8s-blue" fill="currentColor" viewBox="0 0 20 20">${_ICON_CHECK}</svg>
                <span class="text-sm text-devops-text/90">${_safe(o)}</span>
            </li>`).join('')
        : '';

    const stepsHtml = steps.length > 0
        ? steps.map((s, idx) => `
            <div class="flex gap-4">
                <div class="flex flex-col items-center flex-shrink-0">
                    <div class="w-7 h-7 rounded-full bg-k8s-blue text-white text-xs font-plex-mono font-bold flex items-center justify-center">${_safe(idx + 1)}</div>
                    ${idx < steps.length - 1 ? '<div class="w-px flex-1 bg-devops-border-strong my-1"></div>' : ''}
                </div>
                <div class="min-w-0 pb-5">
                    <p class="text-sm font-medium text-devops-text">${_safe(s?.title ?? s?.step_id ?? '')}</p>
                    ${s?.learner_goal ? `<p class="text-sm text-devops-muted mt-1 leading-relaxed">${_safe(s.learner_goal)}</p>` : ''}
                    ${s?.check_count > 0 ? `<span class="inline-block mt-2 text-xs font-plex-mono text-devops-faint">${_safe(s.check_count)} 项自动校验</span>` : ''}
                </div>
            </div>`
          ).join('')
        : '';

    const eligibilityWarning = deferred
        ? _alertBox({
              icon: _ICON_INFO, bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400',
              title: '运行环境检查已延迟',
              bodyHtml: _safe('真实环境检查会在你点击"开始实验"时才执行，届时你的可开始状态可能发生变化。'),
          })
        : '';

    const ineligibleReasons = !canStart && Array.isArray(eligibility?.issues)
        ? eligibility.issues.filter(i => i?.severity === 'error')
              .map(i => `<li class="text-sm text-red-400">${_safe(i?.message ?? i)}</li>`).join('')
        : '';

    const metaBadges = [
        steps.length > 0 ? _badge(`${steps.length} 个步骤`, 'bg-devops-surface-2 text-devops-muted border border-devops-border-strong') : '',
        lab?.estimated_difficulty ? _badge(lab.estimated_difficulty, 'bg-devops-surface-2 text-devops-muted border border-devops-border-strong') : '',
    ].filter(Boolean).join(' ');

    return `
    <div class="space-y-6 font-plex">
        <div>
            <h2 class="text-2xl font-semibold text-devops-text">${_safe(lab?.title ?? 'Lab')}</h2>
            ${metaBadges ? `<div class="flex items-center gap-2 mt-2">${metaBadges}</div>` : ''}
            ${lab?.summary ? `<p class="text-devops-muted mt-3 leading-relaxed">${_safe(lab.summary)}</p>` : ''}
        </div>

        ${lab?.experiment_background ? `
        <div class="bg-k8s-blue/10 border border-k8s-blue/25 rounded-lg p-4">
            <h3 class="text-sm font-semibold text-blue-300 mb-1">背景</h3>
            <p class="text-sm text-devops-text/90 leading-relaxed">${_safe(lab.experiment_background)}</p>
        </div>` : ''}

        ${eligibilityWarning}

        ${objectives ? `
        <div>
            <h3 class="font-semibold text-devops-text mb-3">学习目标</h3>
            <ul class="space-y-2">${objectives}</ul>
        </div>` : ''}

        ${stepsHtml ? `
        <div>
            <h3 class="font-semibold text-devops-text mb-3">实验步骤</h3>
            <div>${stepsHtml}</div>
        </div>` : ''}

        <div class="border-t border-devops-border pt-5">
            ${!canStart && ineligibleReasons ? _alertBox({
                icon: _ICON_ERROR, bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400',
                title: '暂不满足开始条件',
                // ineligibleReasons is already built from _safe()-escaped <li> items above.
                bodyHtml: `<ul class="list-disc pl-4 space-y-0.5 mt-1">${ineligibleReasons}</ul>`,
            }) : ''}
            <div class="mt-4">
                ${eligibility?.existing_session_id ? `
                <a href="/labgen-session.html?sessionId=${encodeURIComponent(eligibility.existing_session_id)}"
                   class="inline-block px-5 py-2.5 rounded-lg font-medium text-sm bg-green-600 text-white hover:bg-green-500 transition">
                    继续实验
                </a>` : `
                <button
                    data-action="start-lab"
                    data-startable="${canStart}"
                    ${!canStart ? 'disabled' : ''}
                    class="px-5 py-2.5 rounded-lg font-medium text-sm transition
                        ${canStart
                            ? 'bg-k8s-blue text-white hover:bg-blue-500'
                            : 'bg-devops-surface-2 text-devops-faint cursor-not-allowed'}">
                    开始实验
                </button>`}
            </div>
        </div>
    </div>`;
}

// ─── Learner: Session ─────────────────────────────────────────────────────────

/**
 * Returns the action button enabled/disabled states for a session snapshot.
 * Pure function — no DOM side-effects.
 *
 * @param {object} snapshot - LearnerSessionSnapshot
 * @returns {{ canCheck: boolean, canComplete: boolean, canAbort: boolean, readyToComplete: boolean }}
 */
export function getSessionActionStates(snapshot) {
    const actions        = snapshot?.action_availability ?? {};
    const runtimeSummary = snapshot?.runtime_summary ?? {};
    return {
        canCheck:        actions?.can_check_current_step === true,
        canComplete:     actions?.can_complete           === true,
        canAbort:        actions?.can_abort              === true,
        readyToComplete: runtimeSummary?.ready_to_complete === true,
    };
}

/**
 * Renders the steps list for the drawer content area.
 * Action buttons are static HTML in the drawer footer (see labgen-session.html).
 *
 * Field mapping (backend model → this function):
 *   snapshot.session_state           → status badge
 *   snapshot.title                   → lab title (inside drawer content)
 *   snapshot.runtime_summary.failure_reason → failure banner
 *   step.status === 'passed'         → step marked as passed
 *   step.is_current                  → step marked as current
 *   step.check_summary               → inline verifier result under current step
 *
 * @param {object} snapshot - LearnerSessionSnapshot
 * @returns {string} HTML string
 */
export function renderSessionView(snapshot) {
    if (!snapshot) return renderErrorState('Session not found', 'dark');

    const runtimeSummary = snapshot?.runtime_summary ?? {};

    const steps = Array.isArray(snapshot?.steps)
        ? snapshot.steps.map((s, idx) => {
            const isCurrent  = s?.is_current === true;
            const isPassed   = s?.status === 'passed';
            const border     = isCurrent ? 'border-k8s-blue/50' : isPassed ? 'border-green-500/30' : 'border-devops-border';
            const icon       = isPassed ? '✓' : isCurrent ? '→' : String(idx + 1);
            const statusText = isPassed ? 'passed' : isCurrent ? 'current' : 'pending';

            // Show step instructions/commands for the active step (expanded) and
            // for already-passed steps (collapsed — still reachable, since some
            // steps like a manual "create the Deployment/Service" setup step have
            // no automated verify criteria and pass immediately on click; the
            // learner must still be able to find and re-run those commands later
            // if a subsequent step depends on them). Locked/pending steps stay
            // fully hidden since their commands aren't actionable yet.
            const showBody = isCurrent || isPassed;
            const stepDo = showBody && s?.step_do
                ? `<p class="text-sm text-devops-muted mt-2 leading-relaxed">${_safe(s.step_do)}</p>`
                : '';
            const stepCmds = showBody && Array.isArray(s?.step_commands) && s.step_commands.length > 0
                ? `<div class="mt-2 space-y-1">${
                      s.step_commands.map(cmd => `<code class="block text-xs bg-devops-bg text-green-400 rounded px-3 py-1.5 font-plex-mono border border-devops-border">${_safe(cmd)}</code>`).join('')
                  }</div>`
                : '';
            const stepHint = showBody && s?.step_troubleshoot
                ? `<details class="mt-2">
                       <summary class="text-xs text-devops-faint cursor-pointer select-none hover:text-devops-muted">操作提示</summary>
                       <p class="text-xs text-devops-muted mt-1 pl-2 border-l-2 border-devops-border-strong leading-relaxed">${_safe(s.step_troubleshoot)}</p>
                   </details>`
                : '';
            const stepBody = `${stepDo}${stepCmds}${stepHint}${isCurrent ? _renderCheckSummary(s?.check_summary) : ''}`;
            // Default-open (not collapsed): the bug this fixes was learners getting
            // stuck with no visible way to find a passed step's commands at all —
            // a collapsed-by-default <details> risks the same discoverability
            // failure with extra steps. Kept as <details> (not a plain <div>) so
            // it's still collapsible once a learner has already seen it.
            const passedBody = isPassed && stepBody
                ? `<details class="mt-1" open>
                       <summary class="text-xs text-devops-faint cursor-pointer select-none hover:text-devops-muted">本步骤命令</summary>
                       ${stepBody}
                   </details>`
                : '';

            return `
            <div class="flex items-start gap-3 border ${border} rounded p-3 bg-devops-surface" data-step-status="${_safe(statusText)}">
                <span class="text-sm font-bold font-plex-mono w-6 text-center flex-shrink-0 ${isPassed ? 'text-green-400' : isCurrent ? 'text-blue-400' : 'text-devops-faint'}">${_safe(icon)}</span>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-devops-text">${_safe(s?.title ?? s?.step_id ?? '')}</p>
                    ${isCurrent ? stepBody : passedBody}
                </div>
            </div>`;
          }).join('')
        : '';

    const failureReasonValue = runtimeSummary?.failure_reason;
    const failureReason = failureReasonValue
        ? `<div class="bg-orange-500/10 border border-orange-500/30 rounded p-3 text-orange-400 text-sm">
               <strong>异常原因：</strong>${_safe(failureReasonValue)}
           </div>`
        : '';

    return `
    <div class="space-y-3 font-plex">
        <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold text-devops-text">实验步骤</h2>
            ${_statusBadge(snapshot?.session_state ?? 'UNKNOWN')}
        </div>

        ${snapshot?.title ? `<p class="text-base font-medium text-devops-text">${_safe(snapshot.title)}</p>` : ''}

        ${failureReason}

        ${steps ? `<div class="space-y-2 mt-3">${steps}</div>` : ''}
    </div>`;
}

function _renderCheckSummary(summary) {
    if (!summary) return '';
    const result = summary?.last_result;
    if (!result || result === 'not_checked') return '';
    const passed  = result === 'passed';
    const failed  = result === 'failed';
    const color   = passed ? 'text-green-400' : failed ? 'text-red-400' : 'text-devops-faint';
    const icon    = passed ? '✓' : failed ? '✗' : '?';
    const label   = passed ? 'passed' : failed ? 'failed' : _safe(result);
    const reason  = !passed && summary?.failure_reason
        ? `<span class="text-devops-faint ml-1">— ${_safe(summary.failure_reason)}</span>`
        : '';
    const msg     = summary?.safe_message
        ? `<span class="text-devops-faint ml-1">${_safe(summary.safe_message)}</span>`
        : '';
    return `<div class="flex items-center gap-2 text-xs font-plex-mono mt-1 ${color}">
        <span>${icon}</span>
        <span>${label}</span>
        ${reason}${msg}
    </div>`;
}

// ─── Dev: Contract Pack viewer ────────────────────────────────────────────────

/**
 * @param {object} pack - ApiContractPack
 */
export function renderContractPackSummary(pack) {
    if (!pack) return renderErrorState('Failed to load contract pack');

    const endpoints = Array.isArray(pack?.endpoints)
        ? pack.endpoints.map(ep => `
            <tr class="border-t border-gray-100">
                <td class="py-2 pr-4">
                    <span class="font-mono text-xs px-1.5 py-0.5 rounded ${ep.method === 'GET' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'}">${_safe(ep.method)}</span>
                </td>
                <td class="py-2 pr-4 font-mono text-xs text-gray-700">${_safe(ep.path)}</td>
                <td class="py-2 text-xs text-gray-500">${_safe(ep.response_model)}</td>
            </tr>`
          ).join('')
        : '';

    return `
    <div class="space-y-4">
        <div class="flex items-center gap-3">
            <h2 class="text-lg font-semibold">Contract Pack</h2>
            ${_badge('v' + _safe(pack?.version ?? '?'), 'bg-blue-100 text-blue-700')}
        </div>
        <table class="w-full text-left text-sm">
            <thead>
                <tr class="text-xs text-gray-400 uppercase tracking-wide">
                    <th class="pb-2 pr-4">Method</th>
                    <th class="pb-2 pr-4">Path</th>
                    <th class="pb-2">Response Model</th>
                </tr>
            </thead>
            <tbody>${endpoints}</tbody>
        </table>
    </div>`;
}

// ─── Demo Seed Result (DEV-ONLY) ──────────────────────────────────────────────

/**
 * Render a DemoSeedResult summary.
 * Never renders raw IDs directly as data — only as safe display text and safe href paths.
 * next_steps paths are rendered as anchor hrefs (no inline handlers).
 *
 * @param {object} result - DemoSeedResult from POST /api/labgen/demo/seed
 * @returns {string} HTML string (safe to set as innerHTML)
 */
/**
 * Render LLM provider boundary status (admin-only diagnostics).
 * Never renders API keys, raw output, hidden prompts, or provider metadata.
 * @param {object} status - LLMProviderStatusResponse
 */
export function renderLLMProviderStatus(status) {
    if (!status || typeof status !== 'object') {
        return renderErrorState('No provider status available.');
    }

    const modeBadge = status.mode === 'fake_only'
        ? _badge('FAKE_ONLY', 'bg-blue-100 text-blue-800')
        : status.mode === 'dry_run'
            ? _badge('DRY_RUN', 'bg-yellow-100 text-yellow-800')
            : status.mode === 'live_enabled'
                ? _badge('LIVE_ENABLED', 'bg-green-100 text-green-800')
                : status.mode === 'disabled'
                    ? _badge('DISABLED', 'bg-gray-100 text-gray-500')
                    : _badge(_safe(status.mode ?? 'UNKNOWN'), 'bg-gray-100 text-gray-600');

    const liveEnabledBadge = status.live_enabled === true
        ? _badge('ENABLED', 'bg-green-100 text-green-800')
        : _badge('DISABLED (default)', 'bg-gray-100 text-gray-500');

    const dryRunBadge = status.dry_run_available
        ? _badge('available', 'bg-green-100 text-green-700')
        : _badge('not available', 'bg-gray-100 text-gray-500');

    const genBadge = status.generation_supported
        ? _badge('yes', 'bg-green-100 text-green-700')
        : _badge('no', 'bg-gray-100 text-gray-500');

    const repairBadge = status.repair_supported
        ? _badge('yes', 'bg-green-100 text-green-700')
        : _badge('OUT_OF_SCOPE v0.1', 'bg-gray-100 text-gray-500');

    const configIssues = Array.isArray(status.config_issues) && status.config_issues.length > 0
        ? `<div class="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
            <p class="font-medium mb-1">Config Issues</p>
            <ul class="space-y-0.5">
                ${status.config_issues.map(i => `<li>${_safe(i)}</li>`).join('')}
            </ul>
          </div>`
        : '';

    const warnings = Array.isArray(status.warnings) && status.warnings.length > 0
        ? `<div class="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-700">
            <ul class="space-y-0.5">
                ${status.warnings.map(w => `<li>${_safe(w)}</li>`).join('')}
            </ul>
          </div>`
        : '';

    const modelRow = status.configured_model
        ? `<div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Model</p>
                <p class="font-mono text-gray-800">${_safe(status.configured_model)}</p>
           </div>`
        : '';

    const baseUrlRow = status.base_url_origin
        ? `<div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Endpoint (origin)</p>
                <p class="font-mono text-gray-800">${_safe(status.base_url_origin)}</p>
           </div>`
        : '';

    return `<div class="space-y-3">
        <div class="grid grid-cols-2 gap-3 text-xs">
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Provider</p>
                <p class="font-mono text-gray-800">${_safe(status.provider_name ?? 'unknown')}</p>
            </div>
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Mode</p>
                <p>${modeBadge}</p>
            </div>
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Live Enabled</p>
                <p>${liveEnabledBadge}</p>
            </div>
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Dry-Run</p>
                <p>${dryRunBadge}</p>
            </div>
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Generation</p>
                <p>${genBadge}</p>
            </div>
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Repair</p>
                <p>${repairBadge}</p>
            </div>
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Timeout (ms)</p>
                <p class="font-mono text-gray-800">${_safe(String(status.timeout_ms ?? 0))}</p>
            </div>
            <div>
                <p class="font-medium text-gray-500 uppercase tracking-wide mb-1">Max Output</p>
                <p class="font-mono text-gray-800">${_safe(String(status.max_output_tokens ?? 0))}</p>
            </div>
            ${modelRow}
            ${baseUrlRow}
        </div>
        ${configIssues}
        <div class="text-xs text-gray-500 border-t pt-2">
            <span class="font-medium">Safety:</span> ${_safe(status.safety_policy_summary ?? '')}
        </div>
        ${warnings}
    </div>`;
}

export function renderAdapterStatus(status) {
    if (!status || typeof status !== 'object') {
        return renderErrorState('No adapter status available.');
    }

    const modeBadge = status.runtime_mode === 'production'
        ? _badge('PRODUCTION', 'bg-red-100 text-red-800')
        : status.runtime_mode === 'dev'
            ? _badge('DEV', 'bg-blue-100 text-blue-700')
            : status.runtime_mode === 'demo'
                ? _badge('DEMO', 'bg-yellow-100 text-yellow-800')
                : _badge(_safe(status.runtime_mode ?? 'UNKNOWN'), 'bg-gray-100 text-gray-600');

    const adapterBadge = status.namespace_adapter_kind === 'stub'
        ? _badge('stub', 'bg-yellow-100 text-yellow-800')
        : _badge('k8s', 'bg-green-100 text-green-800');

    const safeBadge = status.production_safe
        ? _badge('PRODUCTION SAFE', 'bg-green-100 text-green-800')
        : _badge('NOT PRODUCTION SAFE', 'bg-red-100 text-red-700');

    const productionUnsafeWarning = (status.runtime_mode === 'production' && !status.production_safe)
        ? `<div class="mt-3 p-3 rounded bg-red-50 border border-red-300">
            <p class="text-xs font-bold text-red-700">⚠ PRODUCTION MODE — adapter is not production-safe.</p>
            <p class="text-xs text-red-600 mt-1">Lab starts will be rejected until a k8s adapter with a valid kubeconfig is configured.</p>
           </div>`
        : '';

    const nonProdStubNote = (status.runtime_mode !== 'production' && status.namespace_adapter_kind === 'stub')
        ? `<div class="mt-3 p-3 rounded bg-yellow-50 border border-yellow-300">
            <p class="text-xs font-medium text-yellow-800">non-production stub active</p>
            <p class="text-xs text-yellow-700 mt-0.5">No real K8s operations. Stub must not be used in production.</p>
           </div>`
        : '';

    const issueRows = Array.isArray(status.issues) && status.issues.length > 0
        ? status.issues.map(i => {
            const color = i.severity === 'blocking' ? 'text-red-700' : 'text-yellow-700';
            const badge = i.severity === 'blocking'
                ? _badge('BLOCKING', 'bg-red-100 text-red-700')
                : _badge('warning', 'bg-yellow-100 text-yellow-700');
            return `<li class="text-xs ${color} mt-1">${badge} <span class="font-mono">${_safe(i.code)}</span>: ${_safe(i.message)}</li>`;
          }).join('')
        : '<li class="text-xs text-gray-400">No issues.</li>';

    return `<div class="space-y-2">
        <div class="flex flex-wrap items-center gap-2 text-xs">
            <span class="text-gray-500">Mode:</span> ${modeBadge}
            <span class="text-gray-500 ml-2">Adapter:</span> ${adapterBadge}
            <span class="text-gray-500 ml-2">Safety:</span> ${safeBadge}
        </div>
        ${productionUnsafeWarning}
        ${nonProdStubNote}
        <div class="mt-2">
            <p class="text-xs font-medium text-gray-600 mb-1">Issues</p>
            <ul class="space-y-0.5">${issueRows}</ul>
        </div>
        <p class="text-xs text-gray-400 mt-1">Checked at: ${_safe(status.checked_at ?? '')}</p>
    </div>`;
}

export function renderDemoSeedResult(result) {
    if (!result) return renderErrorState('No seed result received');

    const scenarios = Array.isArray(result.seeded_scenarios)
        ? result.seeded_scenarios.map(s => `<li class="font-mono text-xs">${_safe(s)}</li>`).join('')
        : '<li class="text-gray-400">none</li>';

    const draftIds = Array.isArray(result.created_or_updated_draft_ids)
        ? result.created_or_updated_draft_ids.map(id =>
            `<li><a href="${_safe('/labgen-admin.html?draftId=' + encodeURIComponent(id))}"
                class="font-mono text-xs text-blue-600 hover:underline">${_safe(id)}</a></li>`
          ).join('')
        : '';

    const labIds = Array.isArray(result.created_or_updated_lab_ids)
        ? result.created_or_updated_lab_ids.map(id =>
            `<li><a href="${_safe('/labgen-lab.html?labId=' + encodeURIComponent(id))}"
                class="font-mono text-xs text-blue-600 hover:underline">${_safe(id)}</a></li>`
          ).join('')
        : '';

    const sessionIds = Array.isArray(result.created_or_updated_session_ids)
        ? result.created_or_updated_session_ids.map(id =>
            `<li><a href="${_safe('/labgen-session.html?sessionId=' + encodeURIComponent(id))}"
                class="font-mono text-xs text-blue-600 hover:underline">${_safe(id)}</a></li>`
          ).join('')
        : '';

    const warnings = Array.isArray(result.warnings) && result.warnings.length > 0
        ? `<div class="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded">
            <p class="text-xs font-medium text-yellow-800 mb-1">Warnings</p>
            <ul class="list-disc pl-4 space-y-0.5">
                ${result.warnings.map(w => `<li class="text-xs text-yellow-700">${_safe(w)}</li>`).join('')}
            </ul>
          </div>`
        : '';

    const nextSteps = Array.isArray(result.next_steps) && result.next_steps.length > 0
        ? `<div class="mt-4 border-t pt-4">
            <p class="text-xs font-medium text-gray-600 mb-2">Next steps</p>
            <ul class="space-y-1">
                ${result.next_steps.map(step => {
                    // Guard: only accept root-relative paths — blocks javascript: and data: URIs
                    const safePath = /^\//.test(step.path) ? _safe(step.path) : '#';
                    return `<li><a href="${safePath}" target="_blank"
                        class="text-xs text-blue-600 hover:underline">${_safe(step.label)}</a></li>`;
                }).join('')}
            </ul>
          </div>`
        : '';

    return `
    <div class="space-y-4">
        <div class="grid grid-cols-3 gap-4 text-sm">
            <div>
                <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Seeded Scenarios</p>
                <ul class="space-y-0.5 list-disc pl-4">${scenarios}</ul>
            </div>
            <div>
                <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Draft IDs</p>
                <ul class="space-y-0.5 list-disc pl-4">${draftIds || '<li class="text-gray-400 text-xs">none</li>'}</ul>
                <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mt-2 mb-1">Published Lab IDs</p>
                <ul class="space-y-0.5 list-disc pl-4">${labIds || '<li class="text-gray-400 text-xs">none</li>'}</ul>
            </div>
            <div>
                <p class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Session IDs</p>
                <ul class="space-y-0.5 list-disc pl-4">${sessionIds || '<li class="text-gray-400 text-xs">none</li>'}</ul>
            </div>
        </div>
        ${warnings}
        ${nextSteps}
    </div>`;
}

