/**
 * K8S NetLab - Experiment Documentation Manager
 *
 * Loads and renders Markdown experiment documents in the left doc panel.
 * Depends on: marked.js (window.marked), highlight.js (window.hljs)
 */

class ExperimentDocs {
    constructor() {
        this.experiments = [];
        this.currentExpId = null;
        this.activeVmId = null;         // set by app when terminal connects
        this._pendingJumpExpId = null;  // experiment awaiting jump confirmation
        this.mode = 'experiments';      // 'experiments' | 'deployments'

        // DOM refs
        this.selectEl       = document.getElementById('experiment-select');
        this.contentEl      = document.getElementById('doc-content');
        this.loadingEl      = document.getElementById('doc-loading-indicator');
        this.infoBar        = document.getElementById('doc-info-bar');
        this.infoDiff       = document.getElementById('doc-info-difficulty');
        this.infoDur        = document.getElementById('doc-info-duration');
        this.stepNavEl      = document.getElementById('step-nav');
        this.stepPillsEl    = document.getElementById('step-pills');
        this.progressBarEl  = document.getElementById('step-progress-bar');
        this.progressTextEl = document.getElementById('step-progress-text');
        this.jumpWarningEl  = document.getElementById('exp-jump-warning');
        this.jumpWarningTxt = document.getElementById('exp-jump-warning-text');
        this.btnPrev        = document.getElementById('btn-prev-exp');
        this.btnNext        = document.getElementById('btn-next-exp');

        // Step navigation state
        this.steps          = [];   // [{ el, title, idx }]
        this.currentStepIdx = -1;
        this._scrollBound   = this._onDocScroll.bind(this);

        // Configure marked options
        if (window.marked) {
            marked.setOptions({
                gfm: true,
                breaks: false,
            });
        }

        this.init();
    }

    /**
     * Initialize: load experiment list and bind events.
     */
    async init() {
        await this.loadExperimentList();
        this.bindEvents();
    }

    /**
     * Called by app.js when the user connects a terminal to a VM.
     * Resets per-VM state so highwater marks are tracked per VM.
     * @param {number} vmId
     */
    setActiveVm(vmId) {
        if (this.activeVmId === vmId) return;
        this.activeVmId = vmId;
        // Don't reset currentExpId — user may already be reading a doc
    }

    /**
     * Fetch experiment/deployment list from API and populate the selector.
     */
    async loadExperimentList() {
        const endpoint = this.mode === 'deployments' ? '/api/deployments' : '/api/experiments';
        try {
            const resp = await fetch(endpoint);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            this.experiments = data.experiments || data.deployments || [];
            this.populateSelector();
        } catch (err) {
            console.error('[ExperimentDocs] Failed to load list:', err);
        }
    }

    /**
     * Populate the <select> dropdown with experiment/deployment options.
     */
    populateSelector() {
        const prefix = this.mode === 'deployments' ? '案例' : '实验';
        this.experiments.forEach(exp => {
            const opt = document.createElement('option');
            opt.value = exp.id;
            const stars = '⭐'.repeat(exp.difficulty);
            opt.textContent = `${prefix} ${exp.id}: ${exp.title}  ${stars}`;
            this.selectEl.appendChild(opt);
        });
    }

    /**
     * Switch between 'experiments' and 'deployments' mode.
     * @param {string} mode
     */
    async switchMode(mode) {
        if (this.mode === mode) return;
        this.mode = mode;
        this.currentExpId = null;
        this.showPlaceholder();
        while (this.selectEl.options.length > 1) this.selectEl.remove(1);
        await this.loadExperimentList();
        this._updateNavButtons();
    }

    /**
     * Bind events for dropdown, prev/next buttons, and jump warning actions.
     */
    bindEvents() {
        this.selectEl.addEventListener('change', (e) => {
            const expId = e.target.value;
            if (!expId) {
                this.showPlaceholder();
                return;
            }
            this._handleSelectChange(expId);
        });

        if (this.btnPrev) {
            this.btnPrev.addEventListener('click', () => this.prevExperiment());
        }
        if (this.btnNext) {
            this.btnNext.addEventListener('click', () => this.nextExperiment());
        }

        const confirmBtn = document.getElementById('exp-jump-confirm');
        const cancelBtn  = document.getElementById('exp-jump-cancel');
        if (confirmBtn) confirmBtn.addEventListener('click', () => this._confirmJump());
        if (cancelBtn)  cancelBtn.addEventListener('click',  () => this._cancelJump());

        const tabExp = document.getElementById('tab-experiments');
        const tabDep = document.getElementById('tab-deployments');

        tabExp?.addEventListener('click', () => {
            this.switchMode('experiments');
            tabExp.classList.add('border-k8s-blue', 'text-k8s-blue');
            tabExp.classList.remove('border-transparent', 'text-gray-500');
            tabDep.classList.remove('border-k8s-blue', 'text-k8s-blue');
            tabDep.classList.add('border-transparent', 'text-gray-500');
        });

        tabDep?.addEventListener('click', () => {
            this.switchMode('deployments');
            tabDep.classList.add('border-k8s-blue', 'text-k8s-blue');
            tabDep.classList.remove('border-transparent', 'text-gray-500');
            tabExp.classList.remove('border-k8s-blue', 'text-k8s-blue');
            tabExp.classList.add('border-transparent', 'text-gray-500');
        });
    }

    /**
     * Handle dropdown change: intercept forward jumps that skip experiments.
     * @param {string} expId
     */
    _handleSelectChange(expId) {
        const targetN = parseInt(expId, 10);
        const hwm     = this._getHighwater();

        // Only warn when jumping 2+ ahead of the furthest reached experiment
        if (hwm > 0 && targetN > hwm + 1) {
            this._showJumpWarning(expId, hwm);
        } else {
            this.loadExperiment(expId);
        }
    }

    // ─── Jump Warning ─────────────────────────────────────────────────────────

    _showJumpWarning(expId, hwm) {
        this._pendingJumpExpId = expId;
        const hwmStr = String(hwm).padStart(2, '0');
        this.jumpWarningTxt.textContent =
            `实验 ${expId} 依赖前序实验的 K8s 环境配置（当前进度：实验 ${hwmStr}），` +
            `跳过中间实验可能导致步骤失败。`;
        if (this.jumpWarningEl) this.jumpWarningEl.classList.remove('hidden');
    }

    _confirmJump() {
        if (this.jumpWarningEl) this.jumpWarningEl.classList.add('hidden');
        if (this._pendingJumpExpId) {
            const expId = this._pendingJumpExpId;
            this._pendingJumpExpId = null;
            this.loadExperiment(expId);
        }
    }

    _cancelJump() {
        if (this.jumpWarningEl) this.jumpWarningEl.classList.add('hidden');
        // Restore select to currently loaded experiment
        if (this.selectEl) this.selectEl.value = this.currentExpId || '';
        this._pendingJumpExpId = null;
    }

    // ─── Prev / Next Navigation ───────────────────────────────────────────────

    prevExperiment() {
        if (!this.experiments.length) return;
        const idx = this.currentExpId
            ? this.experiments.findIndex(e => e.id === this.currentExpId)
            : -1;
        if (idx > 0) this.loadExperiment(this.experiments[idx - 1].id);
    }

    nextExperiment() {
        if (!this.experiments.length) return;
        if (!this.currentExpId) {
            this.loadExperiment(this.experiments[0].id);
            return;
        }
        const idx = this.experiments.findIndex(e => e.id === this.currentExpId);
        if (idx >= 0 && idx < this.experiments.length - 1) {
            this.loadExperiment(this.experiments[idx + 1].id);
        }
    }

    /**
     * Update disabled state of prev/next buttons based on current position.
     */
    _updateNavButtons() {
        if (!this.btnPrev || !this.btnNext) return;
        const idx = this.currentExpId
            ? this.experiments.findIndex(e => e.id === this.currentExpId)
            : -1;
        this.btnPrev.disabled = (idx <= 0);
        this.btnNext.disabled = (idx < 0 || idx >= this.experiments.length - 1);
    }

    // ─── Highwater Mark (furthest experiment reached, per VM) ─────────────────

    _hwmKey() {
        return this.activeVmId
            ? `k8s-lab-hwm-vm${this.activeVmId}`
            : 'k8s-lab-hwm';
    }

    _getHighwater() {
        try {
            return parseInt(localStorage.getItem(this._hwmKey()) || '0', 10);
        } catch {
            return 0;
        }
    }

    _updateHighwater(expId) {
        const n = parseInt(expId, 10);
        if (n > this._getHighwater()) {
            try { localStorage.setItem(this._hwmKey(), expId); } catch {}
        }
    }

    /**
     * Fetch and render a specific experiment's Markdown content.
     * @param {string} expId - Two-digit experiment ID, e.g. "01"
     */
    async loadExperiment(expId) {
        if (this.currentExpId === expId) return;

        // Dismiss any pending jump warning
        if (this.jumpWarningEl) this.jumpWarningEl.classList.add('hidden');
        this._pendingJumpExpId = null;

        // Reset step nav for new experiment
        this.steps = [];
        this.currentStepIdx = -1;
        this.contentEl.removeEventListener('scroll', this._scrollBound);
        if (this.stepNavEl) this.stepNavEl.classList.add('hidden');

        this.showLoading();

        try {
            const apiBase = this.mode === 'deployments' ? '/api/deployments' : '/api/experiments';
            const resp = await fetch(`${apiBase}/${expId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            this.currentExpId = expId;
            this.renderMarkdown(data.content);
            this.showInfoBar(data.difficulty, data.duration);

            // Sync dropdown selection (covers navigation via prev/next buttons)
            if (this.selectEl) this.selectEl.value = expId;

            // Update highwater mark and nav buttons
            this._updateHighwater(expId);
            this._updateNavButtons();

        } catch (err) {
            this.contentEl.innerHTML = `
                <div class="flex flex-col items-center justify-center h-full text-red-500 space-y-2">
                    <p class="font-medium">加载失败</p>
                    <p class="text-xs text-gray-400">${err.message}</p>
                </div>`;
            console.error('[ExperimentDocs] Failed to load experiment:', err);
        } finally {
            this.hideLoading();
        }
    }

    /**
     * Render Markdown string into the doc content panel.
     * @param {string} markdown - Raw Markdown text
     */
    renderMarkdown(markdown) {
        if (!window.marked) {
            // Fallback: plain text in <pre> if marked.js not loaded
            this.contentEl.innerHTML = `<pre class="text-xs text-gray-700 whitespace-pre-wrap">${this.escapeHtml(markdown)}</pre>`;
            return;
        }

        const rawHtml = marked.parse(markdown);
        const html = window.DOMPurify ? DOMPurify.sanitize(rawHtml) : rawHtml;
        this.contentEl.innerHTML = html;

        // Apply syntax highlighting to all code blocks
        if (window.hljs) {
            this.contentEl.querySelectorAll('pre code').forEach(block => {
                hljs.highlightElement(block);
            });
        }

        // Add copy buttons to all <pre> blocks
        this.contentEl.querySelectorAll('pre').forEach(pre => {
            this.addCopyButton(pre);
        });

        // Scroll doc panel back to top
        this.contentEl.scrollTop = 0;

        // Build step navigation after content is rendered
        this.buildStepNav();
    }

    /**
     * Append a copy button to a <pre> code block.
     * @param {HTMLElement} pre
     */
    addCopyButton(pre) {
        const btn = document.createElement('button');
        btn.textContent = '复制';
        btn.className = 'copy-btn';

        btn.addEventListener('click', async () => {
            const codeEl = pre.querySelector('code');
            const text = codeEl ? codeEl.textContent : pre.textContent;
            try {
                await navigator.clipboard.writeText(text);
                btn.textContent = '已复制 ✓';
                btn.style.background = 'rgba(50,108,229,0.45)';
                btn.style.color = '#fff';
                setTimeout(() => {
                    btn.textContent = '复制';
                    btn.style.background = '';
                    btn.style.color = '';
                }, 2000);
            } catch {
                btn.textContent = '失败';
                setTimeout(() => { btn.textContent = '复制'; }, 2000);
            }
        });

        pre.appendChild(btn);
    }

    /**
     * Show experiment metadata in the info bar.
     */
    showInfoBar(difficulty, duration) {
        const stars = '⭐'.repeat(difficulty);
        this.infoDiff.textContent = `难度: ${stars}`;
        this.infoDur.textContent = `预计 ${duration}`;
        this.infoBar.classList.remove('hidden');
    }

    /**
     * Show the loading spinner in the selector area.
     */
    showLoading() {
        this.loadingEl.classList.remove('hidden');
        this.contentEl.innerHTML = `
            <div class="flex items-center justify-center h-full text-gray-400 space-x-2">
                <div class="loading" style="width:20px;height:20px;border-width:2px;"></div>
                <span class="text-sm">加载中...</span>
            </div>`;
    }

    /**
     * Hide the loading spinner.
     */
    hideLoading() {
        this.loadingEl.classList.add('hidden');
    }

    /**
     * Show the initial placeholder message.
     */
    showPlaceholder() {
        this.currentExpId = null;
        this.steps = [];
        this.currentStepIdx = -1;
        this.contentEl.removeEventListener('scroll', this._scrollBound);
        if (this.stepNavEl) this.stepNavEl.classList.add('hidden');
        if (this.jumpWarningEl) this.jumpWarningEl.classList.add('hidden');
        this.infoBar.classList.add('hidden');
        this._updateNavButtons();
        this.contentEl.innerHTML = `
            <div class="flex flex-col items-center justify-center h-full text-gray-400 space-y-3">
                <svg class="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                        d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.746 0 3.332.477 4.5 1.253v13C19.832 18.477 18.246 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                </svg>
                <p class="text-sm">从上方选择实验文档开始学习</p>
            </div>`;
    }

    /**
     * Escape HTML special characters for safe display.
     * @param {string} str
     * @returns {string}
     */
    escapeHtml(str) {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ─── Step Navigation ──────────────────────────────────────────────────────

    /**
     * Parse "### Step N:" headings from rendered content and build nav UI.
     * Requires this.currentExpId to be set before calling.
     */
    buildStepNav() {
        if (!this.stepNavEl) return;

        const h3s = Array.from(this.contentEl.querySelectorAll('h3'));
        this.steps = h3s
            .filter(h => /^Step\s+\d+/i.test(h.textContent.trim()))
            .map((h, i) => {
                h.id = `doc-step-${i}`;
                return { el: h, title: h.textContent.trim(), idx: i };
            });

        if (this.steps.length === 0) {
            this.stepNavEl.classList.add('hidden');
            return;
        }

        const completed = this.loadProgress(this.currentExpId);
        this._renderPills(completed);
        this._updateProgressBar(completed);
        this.stepNavEl.classList.remove('hidden');

        // Bind scroll listener to update active step while reading
        this.contentEl.removeEventListener('scroll', this._scrollBound);
        this.contentEl.addEventListener('scroll', this._scrollBound, { passive: true });
    }

    /**
     * Render clickable step pills with checkboxes.
     * @param {Set<number>} completed
     */
    _renderPills(completed) {
        if (!this.stepPillsEl) return;
        this.stepPillsEl.innerHTML = '';

        this.steps.forEach(({ title, idx }) => {
            const pill = document.createElement('button');
            pill.className = 'step-pill'
                + (completed.has(idx) ? ' sp-done' : '')
                + (idx === this.currentStepIdx ? ' sp-active' : '');

            // Checkbox for marking step done
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = completed.has(idx);
            cb.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleStep(idx);
            });

            // Label: "Step N"
            const label = document.createElement('span');
            const m = title.match(/^Step\s+(\d+)/i);
            label.textContent = m ? `Step ${m[1]}` : `Step ${idx + 1}`;

            pill.appendChild(cb);
            pill.appendChild(label);
            pill.addEventListener('click', () => this._scrollToStep(idx));
            this.stepPillsEl.appendChild(pill);
        });
    }

    /**
     * Smooth-scroll doc panel to a step heading and mark it active.
     * @param {number} idx
     */
    _scrollToStep(idx) {
        const step = this.steps[idx];
        if (!step) return;
        step.el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        this._setActiveStep(idx);
    }

    /**
     * Highlight the active step pill (without scrolling).
     * @param {number} idx
     */
    _setActiveStep(idx) {
        this.currentStepIdx = idx;
        if (!this.stepPillsEl) return;
        this.stepPillsEl.querySelectorAll('.step-pill').forEach((p, i) => {
            p.classList.toggle('sp-active', i === idx);
        });
    }

    /**
     * Scroll listener: update active step based on doc scroll position.
     */
    _onDocScroll() {
        if (this.steps.length === 0) return;
        const scrollTop = this.contentEl.scrollTop;
        let active = 0;
        for (let i = this.steps.length - 1; i >= 0; i--) {
            if (this.steps[i].el.offsetTop <= scrollTop + 80) {
                active = i;
                break;
            }
        }
        if (active !== this.currentStepIdx) {
            this._setActiveStep(active);
        }
    }

    /**
     * Toggle completion state of a step and persist to localStorage.
     * @param {number} idx
     */
    _toggleStep(idx) {
        const completed = this.loadProgress(this.currentExpId);
        if (completed.has(idx)) {
            completed.delete(idx);
        } else {
            completed.add(idx);
        }
        this.saveProgress(this.currentExpId, completed);
        this._renderPills(completed);
        this._updateProgressBar(completed);
    }

    /**
     * Update the progress bar width and completion text.
     * @param {Set<number>} completed
     */
    _updateProgressBar(completed) {
        if (!this.progressBarEl || !this.progressTextEl) return;
        const total = this.steps.length;
        const done = completed.size;
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        this.progressBarEl.style.width = pct + '%';
        this.progressTextEl.textContent = `${done}/${total} 完成`;
    }

    // ─── Progress Persistence ─────────────────────────────────────────────────

    /**
     * Load completed step indices from localStorage.
     * @param {string} expId
     * @returns {Set<number>}
     */
    loadProgress(expId) {
        try {
            const raw = localStorage.getItem(`k8s-lab-progress-${expId}`);
            return raw ? new Set(JSON.parse(raw)) : new Set();
        } catch {
            return new Set();
        }
    }

    /**
     * Save completed step indices to localStorage.
     * @param {string} expId
     * @param {Set<number>} completed
     */
    saveProgress(expId, completed) {
        try {
            localStorage.setItem(`k8s-lab-progress-${expId}`, JSON.stringify([...completed]));
        } catch {
            // localStorage may be unavailable (private browsing etc.)
        }
    }
}

// Initialize experiment docs manager when DOM is ready
let experimentDocs;
document.addEventListener('DOMContentLoaded', () => {
    experimentDocs = new ExperimentDocs();
});
