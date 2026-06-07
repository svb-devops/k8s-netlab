/**
 * K8S NetLab - AI Tutor Panel
 *
 * Manages the middle "AI 助教" panel:
 *   - Renders case background markdown in the "案例背景" tab
 *   - Provides SSE-based multi-turn chat in the "AI 对话" tab
 *
 * Listens for 'experiment-loaded' custom events dispatched by docs.js.
 * Depends on: marked.js, DOMPurify
 */

class AiTutor {
    constructor() {
        this.currentCaseId   = null;
        this.isStreaming     = false;

        // DOM refs — panel
        this.tabBg      = document.getElementById('ai-tab-bg');
        this.tabChat    = document.getElementById('ai-tab-chat');
        this.bgPanel    = document.getElementById('ai-bg-panel');
        this.chatPanel  = document.getElementById('ai-chat-panel');

        // DOM refs — background
        this.bgContent  = document.getElementById('ai-bg-content');

        // DOM refs — chat
        this.messagesEl = document.getElementById('ai-chat-messages');
        this.inputEl    = document.getElementById('ai-chat-input');
        this.sendBtn    = document.getElementById('ai-chat-send');
        this.clearBtn   = document.getElementById('btn-clear-chat');

        this._bindEvents();
    }

    // ── Tab switching ──────────────────────────────────────────────────────────

    _showBgTab() {
        this.bgPanel.classList.remove('hidden');
        this.bgPanel.classList.add('flex-1');
        this.chatPanel.classList.add('hidden');
        this.chatPanel.classList.remove('flex');

        this.tabBg.classList.add('text-indigo-600', 'border-indigo-500');
        this.tabBg.classList.remove('text-gray-500', 'border-transparent');
        this.tabChat.classList.add('text-gray-500', 'border-transparent');
        this.tabChat.classList.remove('text-indigo-600', 'border-indigo-500');
    }

    _showChatTab() {
        this.bgPanel.classList.add('hidden');
        this.bgPanel.classList.remove('flex-1');
        this.chatPanel.classList.remove('hidden');
        this.chatPanel.classList.add('flex');

        this.tabChat.classList.add('text-indigo-600', 'border-indigo-500');
        this.tabChat.classList.remove('text-gray-500', 'border-transparent');
        this.tabBg.classList.add('text-gray-500', 'border-transparent');
        this.tabBg.classList.remove('text-indigo-600', 'border-indigo-500');

        // Scroll to bottom of messages
        if (this.messagesEl) {
            this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        }
    }

    // ── Background rendering ───────────────────────────────────────────────────

    renderBackground(markdown) {
        if (!this.bgContent) return;
        if (!markdown) {
            this.bgContent.innerHTML = '<p class="text-gray-400 text-xs text-center pt-8">暂无背景介绍</p>';
            return;
        }

        if (window.marked) {
            const raw = marked.parse(markdown);
            const html = window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
            this.bgContent.innerHTML = html;
        } else {
            this.bgContent.textContent = markdown;
        }

        // Scroll background to top
        const bgPanelEl = document.getElementById('ai-bg-panel');
        if (bgPanelEl) bgPanelEl.scrollTop = 0;
    }

    // ── Chat ───────────────────────────────────────────────────────────────────

    _appendMessage(role, text) {
        if (!this.messagesEl) return;

        // Remove placeholder on first real message
        const placeholder = this.messagesEl.querySelector('.text-center');
        if (placeholder) placeholder.remove();

        const wrapper = document.createElement('div');
        wrapper.className = role === 'user'
            ? 'flex justify-end'
            : 'flex justify-start';

        const bubble = document.createElement('div');
        bubble.className = role === 'user'
            ? 'max-w-[85%] bg-indigo-500 text-white rounded-lg px-2.5 py-1.5 text-xs leading-relaxed whitespace-pre-wrap'
            : 'max-w-[90%] bg-gray-100 text-gray-800 rounded-lg px-2.5 py-1.5 text-xs leading-relaxed';

        if (role === 'assistant') {
            bubble.dataset.streaming = 'true';
        }
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
        bubble.className = 'max-w-[90%] bg-gray-100 text-gray-800 rounded-lg px-2.5 py-1.5 text-xs leading-relaxed';
        bubble.dataset.streaming = 'true';
        bubble.innerHTML = '<span class="animate-pulse text-indigo-400">▌</span>';

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

            const reader = resp.body.getReader();
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
                        if (parsed.error) {
                            accumulated = '⚠️ ' + parsed.error;
                        } else if (parsed.text) {
                            accumulated += parsed.text;
                        }
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

        if (bubble) {
            bubble.textContent = accumulated || '（无回复）';
            delete bubble.dataset.streaming;
        }

        this.isStreaming = false;
        this._setInputEnabled(true);
        this.inputEl?.focus();
    }

    _setInputEnabled(enabled) {
        if (this.inputEl) this.inputEl.disabled = !enabled;
        if (this.sendBtn) this.sendBtn.disabled = !enabled;
    }

    async _clearHistory() {
        try {
            await fetch('/api/ai/chat/history', { method: 'DELETE' });
        } catch {}
        if (this.messagesEl) {
            this.messagesEl.innerHTML = `
                <div class="text-center text-gray-400 text-xs py-4">
                    <p>对话记录已清除</p>
                    <p class="mt-1 text-gray-300">仅回答 K8s 相关问题</p>
                </div>`;
        }
    }

    // ── Event binding ──────────────────────────────────────────────────────────

    _bindEvents() {
        this.tabBg?.addEventListener('click', () => this._showBgTab());
        this.tabChat?.addEventListener('click', () => this._showChatTab());
        this.sendBtn?.addEventListener('click', () => this._sendMessage());
        this.clearBtn?.addEventListener('click', () => this._clearHistory());

        this.inputEl?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._sendMessage();
            }
        });

        // Listen for experiment/deployment loaded events from docs.js
        document.addEventListener('experiment-loaded', (e) => {
            const { caseId, background } = e.detail || {};
            this.currentCaseId = caseId || null;
            this.renderBackground(background || '');
            // Auto-switch to background tab when a new case is loaded
            this._showBgTab();
        });
    }
}

// Initialize after DOM is ready
let aiTutor;
document.addEventListener('DOMContentLoaded', () => {
    aiTutor = new AiTutor();
});
