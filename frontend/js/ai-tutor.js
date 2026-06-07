/**
 * K8S NetLab - AI Tutor (integrated into doc panel)
 *
 * Manages three content views inside the left doc panel:
 *   view-tab-doc  → #doc-content      (existing markdown doc)
 *   view-tab-bg   → #ai-bg-panel      (case background)
 *   view-tab-ai   → #ai-chat-panel    (AI chat)
 *
 * Listens for 'experiment-loaded' custom events from docs.js.
 */

class AiTutor {
    constructor() {
        this.currentCaseId = null;
        this.isStreaming   = false;
        this.currentView   = 'doc'; // 'doc' | 'bg' | 'ai'

        // View tab buttons
        this.tabDoc  = document.getElementById('view-tab-doc');
        this.tabBg   = document.getElementById('view-tab-bg');
        this.tabAi   = document.getElementById('view-tab-ai');

        // View panels
        this.panelDoc  = document.getElementById('doc-content');
        this.panelBg   = document.getElementById('ai-bg-panel');
        this.panelAi   = document.getElementById('ai-chat-panel');

        // Background content
        this.bgContent = document.getElementById('ai-bg-content');

        // Chat elements
        this.messagesEl = document.getElementById('ai-chat-messages');
        this.inputEl    = document.getElementById('ai-chat-input');
        this.sendBtn    = document.getElementById('ai-chat-send');
        this.clearBtn   = document.getElementById('btn-clear-chat');

        // Step-nav element — hidden when not in doc view
        this.stepNav = document.getElementById('step-nav');

        this._bindEvents();
    }

    // ── View switching ─────────────────────────────────────────────────────────

    _showView(view) {
        this.currentView = view;

        // Panel visibility
        this.panelDoc.classList.toggle('hidden', view !== 'doc');
        this.panelBg.classList.toggle('hidden',  view !== 'bg');

        if (view === 'ai') {
            this.panelAi.classList.remove('hidden');
            this.panelAi.classList.add('flex');
        } else {
            this.panelAi.classList.add('hidden');
            this.panelAi.classList.remove('flex');
        }

        // Step nav only makes sense in doc view
        if (this.stepNav) {
            if (view !== 'doc') {
                this.stepNav.dataset.hiddenByAi = this.stepNav.classList.contains('hidden') ? '' : 'yes';
                this.stepNav.classList.add('hidden');
            } else if (this.stepNav.dataset.hiddenByAi === 'yes') {
                this.stepNav.classList.remove('hidden');
                delete this.stepNav.dataset.hiddenByAi;
            }
        }

        // Tab button active styles
        const tabs = [
            { btn: this.tabDoc, name: 'doc' },
            { btn: this.tabBg,  name: 'bg'  },
            { btn: this.tabAi,  name: 'ai'  },
        ];
        tabs.forEach(({ btn, name }) => {
            if (!btn) return;
            const active = name === view;
            btn.classList.toggle('text-k8s-blue',      active);
            btn.classList.toggle('border-k8s-blue',    active);
            btn.classList.toggle('bg-white',           active);
            btn.classList.toggle('font-medium',        active);
            btn.classList.toggle('text-gray-500',      !active);
            btn.classList.toggle('border-transparent', !active);
        });

        // Scroll AI messages to bottom when switching to AI
        if (view === 'ai' && this.messagesEl) {
            this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        }
    }

    // ── Background rendering ───────────────────────────────────────────────────

    renderBackground(markdown) {
        if (!this.bgContent) return;
        if (!markdown) {
            this.bgContent.innerHTML = '<p class="text-gray-400 text-sm text-center pt-12">暂无背景介绍</p>';
            return;
        }
        if (window.marked) {
            const raw  = marked.parse(markdown);
            const html = window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
            this.bgContent.innerHTML = html;
        } else {
            this.bgContent.textContent = markdown;
        }
        if (this.panelBg) this.panelBg.scrollTop = 0;
    }

    // ── Chat ───────────────────────────────────────────────────────────────────

    _appendMessage(role, text) {
        if (!this.messagesEl) return null;
        const placeholder = this.messagesEl.querySelector('.text-center');
        if (placeholder) placeholder.remove();

        const wrapper = document.createElement('div');
        wrapper.className = role === 'user' ? 'flex justify-end' : 'flex justify-start';

        const bubble = document.createElement('div');
        bubble.className = role === 'user'
            ? 'max-w-[80%] bg-indigo-500 text-white rounded-2xl rounded-tr-sm px-3 py-2 text-sm leading-relaxed'
            : 'max-w-[85%] bg-gray-100 text-gray-800 rounded-2xl rounded-tl-sm px-3 py-2 text-sm leading-relaxed';
        bubble.textContent = text;
        wrapper.appendChild(bubble);
        this.messagesEl.appendChild(wrapper);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        return bubble;
    }

    _appendStreamingBubble() {
        if (!this.messagesEl) return null;
        const placeholder = this.messagesEl.querySelector('.text-center');
        if (placeholder) placeholder.remove();

        const wrapper = document.createElement('div');
        wrapper.className = 'flex justify-start';

        const bubble = document.createElement('div');
        bubble.className = 'max-w-[85%] bg-gray-100 text-gray-800 rounded-2xl rounded-tl-sm px-3 py-2 text-sm leading-relaxed';
        bubble.innerHTML = '<span class="inline-block w-1.5 h-4 bg-indigo-400 rounded animate-pulse"></span>';
        wrapper.appendChild(bubble);
        this.messagesEl.appendChild(wrapper);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        return bubble;
    }

    async _sendMessage() {
        if (this.isStreaming) return;
        const msg = (this.inputEl?.value || '').trim();
        if (!msg) return;

        this.inputEl.value = '';
        this._setInputEnabled(false);
        this.isStreaming = true;

        this._appendMessage('user', msg);
        const bubble = this._appendStreamingBubble();
        let accumulated = '';

        try {
            const resp = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: msg,
                    case_id: this.currentCaseId || null,
                }),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }

            const reader  = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const payload = line.slice(6).trim();
                    if (payload === '[DONE]') break;
                    try {
                        const parsed = JSON.parse(payload);
                        if (parsed.error)     accumulated = '⚠️ ' + parsed.error;
                        else if (parsed.text) accumulated += parsed.text;
                    } catch {}

                    if (bubble) {
                        bubble.textContent = accumulated || '';
                        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
                    }
                }
            }
        } catch (err) {
            accumulated = '⚠️ 连接失败: ' + err.message;
        }

        if (bubble) bubble.textContent = accumulated || '（无回复）';
        this.isStreaming = false;
        this._setInputEnabled(true);
        this.inputEl?.focus();
    }

    _setInputEnabled(enabled) {
        if (this.inputEl) this.inputEl.disabled = !enabled;
        if (this.sendBtn) this.sendBtn.disabled = !enabled;
    }

    async _clearHistory() {
        try { await fetch('/api/ai/chat/history', { method: 'DELETE' }); } catch {}
        if (this.messagesEl) {
            this.messagesEl.innerHTML = `
                <div class="text-center text-gray-400 text-sm py-8">
                    <p>对话已清除</p>
                    <p class="text-xs text-gray-300 mt-1">仅回答 K8s 相关问题</p>
                </div>`;
        }
    }

    // ── Event binding ──────────────────────────────────────────────────────────

    _bindEvents() {
        this.tabDoc?.addEventListener('click', () => this._showView('doc'));
        this.tabBg?.addEventListener('click',  () => this._showView('bg'));
        this.tabAi?.addEventListener('click',  () => this._showView('ai'));

        this.sendBtn?.addEventListener('click', () => this._sendMessage());
        this.clearBtn?.addEventListener('click', () => this._clearHistory());

        this.inputEl?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._sendMessage();
            }
        });

        // Receive experiment/deployment loaded event from docs.js
        document.addEventListener('experiment-loaded', (e) => {
            const { caseId, background } = e.detail || {};
            this.currentCaseId = caseId || null;
            this.renderBackground(background || '');
            // Stay on current view — don't auto-jump to background tab
        });
    }
}

let aiTutor;
document.addEventListener('DOMContentLoaded', () => {
    aiTutor = new AiTutor();
});
