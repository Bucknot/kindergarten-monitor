// Smart LLM Agent Chat Controller
class ChatController {
    constructor() {
        this.sessionId = null;
        this.session = null;
        this.history = [];
        this.isLoading = false;
    }

    init() {
        const sendBtn = document.getElementById('chat-send-btn');
        const input = document.getElementById('chat-input');

        if (sendBtn) {
            sendBtn.addEventListener('click', () => this.handleSend());
        }

        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.handleSend();
                }
            });
        }
    }

    setSession(sessionId, session) {
        this.sessionId = sessionId;
        this.session = session;
        this.history = [];
        this.renderInitialWelcome();
    }

    renderInitialWelcome() {
        const container = document.getElementById('chat-messages-container');
        if (!container) return;

        const childName = this.session?.target_child_name ? ` (עבור ${this.session.target_child_name})` : '';
        const title = this.session?.title || 'הקלטת היום';

        container.innerHTML = `
            <div class="flex items-start gap-3 p-4 rounded-2xl bg-indigo-50/70 border border-indigo-100 text-slate-800">
                <div class="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center font-bold text-base shadow-sm shrink-0">
                    🤖
                </div>
                <div class="space-y-1.5 text-xs sm:text-sm leading-relaxed">
                    <p class="font-bold text-indigo-950">
                        שלום! אני סוכן ה-AI המומחה לניתוח השמע והאירועים בהקלטה "${title}"${childName}.
                    </p>
                    <p class="text-slate-600 text-[13px]">
                        לרשותי כלים מיוחדים לחפש בתמליל המלא של כל שעות היום בגן, לקרוא מהלכי שיחה מלאים סביב כל שעה, ולעיין בפרקי הדוח הפדגוגי.
                    </p>
                    <p class="text-indigo-900 font-semibold text-[12px] pt-1">
                        💡 תוכל לשאול אותי כל שאלה, לבקש בדיקת אירועים חריגים, או ללחוץ על אחת משאלות הדוגמה למטה.
                    </p>
                </div>
            </div>
        `;
    }

    setQuestionPrompt(promptText) {
        const input = document.getElementById('chat-input');
        if (input) {
            input.value = promptText;
            input.focus();
        }
    }

    sendQuickQuestion(promptText) {
        const input = document.getElementById('chat-input');
        if (input) {
            input.value = promptText;
            this.handleSend();
        }
    }

    async handleSend() {
        if (this.isLoading) return;
        const input = document.getElementById('chat-input');
        if (!input) return;

        const text = input.value.trim();
        if (!text) return;

        if (!this.sessionId) {
            alert('אנא פתח הקלטה תחילה');
            return;
        }

        // Add user message to UI
        this.appendMessage('user', text);
        this.history.push({ role: 'user', content: text });
        input.value = '';

        // Show thinking indicator
        this.isLoading = true;
        this.updateSendButtonState(true);
        const thinkingId = this.showThinkingIndicator();

        try {
            const orKey = document.getElementById('cfg-openrouter-key')?.value.trim();
            const orModel = document.getElementById('cfg-openrouter-model')?.value.trim();

            const res = await API.sendChatMessage(this.sessionId, {
                message: text,
                history: this.history.slice(-8),
                openrouter_api_key: orKey || undefined,
                openrouter_model: orModel || undefined
            });

            this.removeThinkingIndicator(thinkingId);
            this.appendAssistantResponse(res);
            this.history.push({ role: 'assistant', content: res.reply });
        } catch (err) {
            console.error('Chat error:', err);
            this.removeThinkingIndicator(thinkingId);
            this.appendErrorMessage('שגיאה בתקשורת עם סוכן ה-AI: ' + err.message);
        } finally {
            this.isLoading = false;
            this.updateSendButtonState(false);
            if (input) input.focus();
        }
    }

    appendMessage(role, text) {
        const container = document.getElementById('chat-messages-container');
        if (!container) return;

        const msgDiv = document.createElement('div');
        msgDiv.className = 'flex items-start gap-3 justify-end';

        msgDiv.innerHTML = `
            <div class="max-w-[85%] sm:max-w-[75%] bg-indigo-600 text-white p-3.5 sm:p-4 rounded-2xl rounded-tl-sm text-xs sm:text-sm leading-relaxed shadow-sm">
                <p class="whitespace-pre-wrap">${this.escapeHtml(text)}</p>
            </div>
            <div class="w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-xs shrink-0">
                אתה
            </div>
        `;

        container.appendChild(msgDiv);
        this.scrollToBottom();
    }

    appendAssistantResponse(response) {
        const container = document.getElementById('chat-messages-container');
        if (!container) return;

        const msgDiv = document.createElement('div');
        msgDiv.className = 'flex items-start gap-3';

        // Render tool executions summary badge if present
        let toolsHtml = '';
        if (response.tool_executions && response.tool_executions.length > 0) {
            const toolsList = response.tool_executions.map(t => {
                let icon = '🔍';
                if (t.tool === 'get_context_around_time') icon = '⏱️';
                if (t.tool === 'get_report_section') icon = '📑';
                if (t.tool === 'get_session_speakers') icon = '👥';
                return `<li class="flex items-center gap-1.5"><span class="shrink-0">${icon}</span> <span>${this.escapeHtml(t.summary)}</span></li>`;
            }).join('');

            toolsHtml = `
                <details class="mb-3 text-[11px] bg-slate-50 border border-slate-200/80 rounded-xl p-2.5 text-slate-600 group">
                    <summary class="font-semibold text-slate-700 cursor-pointer flex items-center justify-between select-none">
                        <span class="flex items-center gap-1.5 text-indigo-700">
                            <span>🛠️</span>
                            <span>פעולות חיפוש ותחקור שביצע הסוכן (${response.tool_executions.length}):</span>
                        </span>
                        <span class="text-[10px] text-slate-400 group-open:rotate-180 transition-transform">▼</span>
                    </summary>
                    <ul class="mt-2 space-y-1 pr-2 border-r-2 border-indigo-200 font-mono text-[11px]">
                        ${toolsList}
                    </ul>
                </details>
            `;
        }

        // Format body with clickable timestamps
        const formattedBody = this.formatMarkdownAndTimestamps(response.reply);

        // Citations pills
        let citationsHtml = '';
        if (response.citations && response.citations.length > 0) {
            const citationButtons = response.citations.map(c => `
                <button type="button" 
                        onclick="app.jumpToPlayerTimestamp(${c.timestamp_seconds})"
                        title="${this.escapeHtml(c.text || '')}"
                        class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 transition-colors shadow-2xs">
                    <span class="text-indigo-500">🎧</span>
                    <span class="font-mono dir-ltr">${c.timestamp_formatted}</span>
                    <span class="text-slate-600 font-normal">| ${this.escapeHtml(c.speaker_name)}</span>
                </button>
            `).join('');

            citationsHtml = `
                <div class="mt-3 pt-3 border-t border-slate-100 space-y-1.5">
                    <span class="block text-[11px] font-bold text-slate-500">האזנה ישירה לקטעים שצוטטו בהקלטה:</span>
                    <div class="flex flex-wrap gap-1.5">
                        ${citationButtons}
                    </div>
                </div>
            `;
        }

        msgDiv.innerHTML = `
            <div class="w-9 h-9 rounded-xl bg-indigo-600 text-white flex items-center justify-center font-bold text-base shadow-sm shrink-0">
                🤖
            </div>
            <div class="max-w-[90%] sm:max-w-[85%] bg-white border border-slate-200 p-4 sm:p-5 rounded-2xl rounded-tr-sm text-xs sm:text-sm text-slate-800 leading-relaxed shadow-sm">
                ${toolsHtml}
                <div class="chat-markdown-body space-y-2">
                    ${formattedBody}
                </div>
                ${citationsHtml}
            </div>
        `;

        container.appendChild(msgDiv);
        this.scrollToBottom();
    }

    appendErrorMessage(errMsg) {
        const container = document.getElementById('chat-messages-container');
        if (!container) return;

        const msgDiv = document.createElement('div');
        msgDiv.className = 'flex items-start gap-3';
        msgDiv.innerHTML = `
            <div class="w-8 h-8 rounded-xl bg-rose-600 text-white flex items-center justify-center font-bold text-xs shrink-0">
                ⚠️
            </div>
            <div class="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs">
                ${this.escapeHtml(errMsg)}
            </div>
        `;
        container.appendChild(msgDiv);
        this.scrollToBottom();
    }

    showThinkingIndicator() {
        const container = document.getElementById('chat-messages-container');
        if (!container) return null;

        const id = 'thinking-' + Date.now();
        const div = document.createElement('div');
        div.id = id;
        div.className = 'flex items-start gap-3 animate-pulse';
        div.innerHTML = `
            <div class="w-9 h-9 rounded-xl bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-base shrink-0">
                🤖
            </div>
            <div class="bg-indigo-50 border border-indigo-100 px-4 py-3 rounded-2xl text-xs text-indigo-800 flex items-center gap-2">
                <svg class="animate-spin h-3.5 w-3.5 text-indigo-600" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>הסוכן סורק את התמליל ומפעיל כלי בדיקה...</span>
            </div>
        `;
        container.appendChild(div);
        this.scrollToBottom();
        return id;
    }

    removeThinkingIndicator(id) {
        if (!id) return;
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    updateSendButtonState(loading) {
        const btn = document.getElementById('chat-send-btn');
        if (!btn) return;
        if (loading) {
            btn.disabled = true;
            btn.classList.add('opacity-60', 'cursor-not-allowed');
        } else {
            btn.disabled = false;
            btn.classList.remove('opacity-60', 'cursor-not-allowed');
        }
    }

    formatMarkdownAndTimestamps(rawText) {
        if (!rawText) return '';

        // 1. Convert markdown bold and code
        let html = this.escapeHtml(rawText);
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        html = html.replace(/`([^`]+)`/g, '<code class="bg-slate-100 px-1 py-0.5 rounded text-indigo-700 font-mono text-[11px]">$1</code>');

        // 2. Format lines and bullet points
        const lines = html.split('\n');
        const formattedLines = lines.map(line => {
            const trimmed = line.trim();
            if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
                return `<li class="mr-4 list-disc">${trimmed.substring(2)}</li>`;
            } else if (/^\d+\.\s/.test(trimmed)) {
                return `<li class="mr-4 list-decimal">${trimmed.replace(/^\d+\.\s/, '')}</li>`;
            } else if (trimmed.startsWith('### ')) {
                return `<h4 class="font-extrabold text-sm text-slate-900 mt-2 mb-1">${trimmed.substring(4)}</h4>`;
            } else if (trimmed.startsWith('## ')) {
                return `<h3 class="font-extrabold text-base text-slate-900 mt-3 mb-1.5">${trimmed.substring(3)}</h3>`;
            } else if (!trimmed) {
                return '<div class="h-1.5"></div>';
            }
            return `<p>${line}</p>`;
        });
        html = formattedLines.join('');

        // 3. Make timestamps clickable badges: [HH:MM:SS] or HH:MM:SS
        html = html.replace(/\[?(\d{1,2}:\d{2}:\d{2})\]?/g, (match, hms) => {
            const secs = this.parseHmsToSeconds(hms);
            return `<button type="button" 
                            onclick="app.jumpToPlayerTimestamp(${secs})" 
                            class="inline-flex items-center gap-1 font-mono text-indigo-700 font-bold bg-indigo-50 hover:bg-indigo-100 hover:text-indigo-900 px-1.5 py-0.5 rounded border border-indigo-200 transition-colors mx-0.5 cursor-pointer dir-ltr" 
                            title="לחץ להאזנה ישירה בנגן לשעה ${hms}">⏱️ ${hms}</button>`;
        });

        return html;
    }

    parseHmsToSeconds(hms) {
        const parts = hms.split(':').map(Number);
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
        if (parts.length === 2) return parts[0] * 60 + parts[1];
        return 0;
    }

    scrollToBottom() {
        const container = document.getElementById('chat-messages-container');
        if (container) {
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
        }
    }

    escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
}

window.chatController = new ChatController();
