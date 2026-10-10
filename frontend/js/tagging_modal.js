// Voice Tagging & Focus Configuration Screen Controller
class TaggingController {
    constructor() {
        this.currentSession = null;
        this.selectedChildSpeakerId = null;
        this.snippetAudios = {};
    }

    renderTaggingScreen(session) {
        this.currentSession = session;
        const container = document.getElementById('tagging-speakers-list');
        if (!container) return;

        container.innerHTML = '';
        const totalDuration = session.duration_seconds || 1;

        // Extract context suggestions from session or saved profile
        const context = session.context_metadata || (function() {
            try { return JSON.parse(localStorage.getItem('kindergarten_profile') || '{}'); } catch(e) { return {}; }
        })();
        const suggestions = this.extractSuggestions(context);

        // Top quick-tag suggestions bar
        if (suggestions.length > 0) {
            const rosterBar = document.createElement('div');
            rosterBar.className = 'p-3.5 bg-gradient-to-r from-indigo-50/90 via-purple-50/70 to-blue-50/90 rounded-2xl border border-indigo-200/90 mb-4 shadow-xs';
            rosterBar.innerHTML = `
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-black text-indigo-950 flex items-center gap-1.5">
                        <span>🎒 תיוג מהיר מתוך פרופיל הגן:</span>
                        <span class="text-[10px] text-indigo-600 font-normal">לחץ על תגית כדי לשייך אותה לדובר הבא שטרם תויג</span>
                    </span>
                </div>
                <div class="flex flex-wrap gap-1.5" id="roster-quick-chips">
                    ${suggestions.map(sug => `
                        <button type="button"
                                onclick="taggingController.applySuggestionToNextAvailable('${sug.name.replace(/'/g, "\\'")}', '${sug.role.replace(/'/g, "\\'")}', ${sug.is_focus})"
                                class="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-xs font-bold transition-all shadow-2xs border ${
                                    sug.category === 'child'
                                        ? 'bg-emerald-100 hover:bg-emerald-200 text-emerald-900 border-emerald-300'
                                        : sug.category === 'parent'
                                        ? 'bg-blue-100 hover:bg-blue-200 text-blue-900 border-blue-300'
                                        : sug.category === 'staff'
                                        ? 'bg-purple-100 hover:bg-purple-200 text-purple-900 border-purple-300'
                                        : 'bg-amber-100 hover:bg-amber-200 text-amber-900 border-amber-300'
                                }">
                            <span>${sug.label}</span>
                            <span class="text-[9px] opacity-75 font-normal">(${sug.badge})</span>
                        </button>
                    `).join('')}
                </div>
            `;
            container.appendChild(rosterBar);
        }

        session.speakers.forEach((spk, idx) => {
            const pct = Math.round((spk.total_speech_seconds / totalDuration) * 100);
            const isDominant = idx === 0;

            const card = document.createElement('div');
            card.className = `p-4 rounded-xl border transition-all duration-200 ${
                spk.is_child_in_focus
                    ? 'border-emerald-500 bg-emerald-50/40 ring-2 ring-emerald-500/20'
                    : 'border-slate-200 bg-white hover:border-indigo-300'
            }`;
            card.id = `speaker-card-${spk.id}`;

            const cardQuickChips = suggestions.length > 0 ? `
                <div class="mt-2.5 pt-2 border-t border-slate-100 flex flex-wrap items-center gap-1.5">
                    <span class="text-[10px] text-slate-400 font-medium">שיוך מהיר לדובר זה:</span>
                    ${suggestions.map(sug => `
                        <button type="button"
                                onclick="taggingController.applySuggestionToSpeaker('${spk.id}', '${sug.name.replace(/'/g, "\\'")}', '${sug.role.replace(/'/g, "\\'")}', ${sug.is_focus})"
                                class="px-2 py-0.5 text-[10px] rounded-lg bg-slate-100 hover:bg-indigo-100 text-slate-700 hover:text-indigo-900 transition-colors border border-slate-200">
                            ${sug.name} (${sug.badge})
                        </button>
                    `).join('')}
                </div>
            ` : '';

            card.innerHTML = `
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm ${
                            isDominant ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-700'
                        }">
                            ${idx + 1}
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="font-semibold text-slate-800">${spk.diarization_tag}</span>
                                ${isDominant ? '<span class="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">הדובר הדומיננטי</span>' : ''}
                            </div>
                            <span class="text-xs text-slate-500">
                                סה"כ דיבור: ${Math.round(spk.total_speech_seconds)} שניות (~${pct}%) | ${spk.utterance_count} מקטעים
                            </span>
                        </div>
                    </div>

                    <!-- Snippet Playback Button -->
                    <div>
                        <button type="button" 
                                onclick="taggingController.playSnippet('${spk.session_id}', '${spk.diarization_tag}', this)"
                                class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 text-slate-700 hover:bg-indigo-50 hover:text-indigo-600 transition-colors">
                            <svg class="w-4 h-4 play-icon" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"></path>
                            </svg>
                            <span class="btn-text">האזן לדגימה (6 שנ')</span>
                        </button>
                    </div>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
                    <!-- Assigned Name -->
                    <div class="sm:col-span-5">
                        <label class="block text-xs font-medium text-slate-600 mb-1">שם או כינוי</label>
                        <input type="text" 
                               id="spk-name-${spk.id}"
                               value="${spk.assigned_name || (idx === 0 ? 'גננת מיכל' : (idx === 1 ? 'סייעת' : 'ילד/ה'))}"
                               placeholder="לדוגמה: הגננת מיכל / הבן שלי איתי"
                               class="w-full text-sm px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:outline-none" />
                    </div>

                    <!-- Role Dropdown -->
                    <div class="sm:col-span-4">
                        <label class="block text-xs font-medium text-slate-600 mb-1">תפקיד / קטגוריה</label>
                        <select id="spk-role-${spk.id}"
                                class="w-full text-sm px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white">
                            <option value="גננת ראשית" ${spk.role === 'גננת ראשית' || (!spk.role && idx === 0) ? 'selected' : ''}>גננת ראשית</option>
                            <option value="סייעת" ${spk.role === 'סייעת' || (!spk.role && idx === 1) ? 'selected' : ''}>סייעת</option>
                            <option value="ילד/ה במוקד" ${spk.is_child_in_focus || spk.role === 'ילד/ה במוקד' || (!spk.role && idx === 2) ? 'selected' : ''}>ילד/ה במוקד</option>
                            <option value="הורה" ${spk.role === 'הורה' ? 'selected' : ''}>הורה (אבא / אמא)</option>
                            <option value="חבר/ה לגן" ${spk.role === 'חבר/ה לגן' || (!spk.role && idx > 2) ? 'selected' : ''}>חבר/ה לגן</option>
                            <option value="איש צוות / חוג" ${spk.role === 'איש צוות / חוג' ? 'selected' : ''}>איש צוות / מפעיל חוג</option>
                            <option value="קולות רקע" ${spk.role === 'קולות רקע' ? 'selected' : ''}>קולות רקע</option>
                        </select>
                    </div>

                    <!-- Child in Focus Radio -->
                    <div class="sm:col-span-3 flex items-center justify-end">
                        <label class="relative flex items-center gap-2 cursor-pointer p-2 rounded-lg hover:bg-slate-50 w-full sm:w-auto">
                            <input type="radio" 
                                   name="focus_child_radio" 
                                   value="${spk.id}"
                                   ${spk.is_child_in_focus || idx === 2 ? 'checked' : ''}
                                   onchange="taggingController.onSelectFocusChild('${spk.id}')"
                                   class="w-4 h-4 text-emerald-600 focus:ring-emerald-500 border-slate-300">
                            <span class="text-xs font-semibold text-emerald-800">
                                הילד/ה שלי במוקד
                            </span>
                        </label>
                    </div>
                </div>
                ${cardQuickChips}
            `;
            container.appendChild(card);
        });

        // Initialize focus prompt if already present
        if (session.focus_prompt) {
            const promptEl = document.getElementById('tagging-focus-prompt');
            if (promptEl) promptEl.value = session.focus_prompt;
        }
    }

    playSnippet(sessionId, speakerTag, btn) {
        const key = `${sessionId}_${speakerTag}`;
        if (this.snippetAudios[key] && !this.snippetAudios[key].paused) {
            this.snippetAudios[key].pause();
            btn.querySelector('.btn-text').textContent = 'האזן לדגימה';
            return;
        }

        // Stop all other snippets
        Object.values(this.snippetAudios).forEach(a => a.pause());
        document.querySelectorAll('.btn-text').forEach(el => el.textContent = 'האזן לדגימה');

        const audio = new Audio(`/api/audio/snippet/${sessionId}/${speakerTag}`);
        this.snippetAudios[key] = audio;
        btn.querySelector('.btn-text').textContent = 'מנגן... (עצור)';

        audio.play().catch(e => console.log('Playback error:', e));
        audio.onended = () => {
            btn.querySelector('.btn-text').textContent = 'האזן לדגימה';
        };
    }

    onSelectFocusChild(speakerId) {
        this.selectedChildSpeakerId = speakerId;
        // Update styling on cards
        document.querySelectorAll('[id^="speaker-card-"]').forEach(card => {
            if (card.id === `speaker-card-${speakerId}`) {
                card.classList.add('border-emerald-500', 'bg-emerald-50/40', 'ring-2', 'ring-emerald-500/20');
                card.classList.remove('border-slate-200', 'bg-white');
            } else {
                card.classList.remove('border-emerald-500', 'bg-emerald-50/40', 'ring-2', 'ring-emerald-500/20');
                card.classList.add('border-slate-200', 'bg-white');
            }
        });
        // Auto-set role dropdown to 'ילד/ה במוקד'
        const roleSelect = document.getElementById(`spk-role-${speakerId}`);
        if (roleSelect) roleSelect.value = 'ילד/ה במוקד';
    }

    setFocusPreset(text) {
        const promptEl = document.getElementById('tagging-focus-prompt');
        if (!promptEl) return;
        if (promptEl.value.trim()) {
            promptEl.value += ' | ' + text;
        } else {
            promptEl.value = text;
        }
    }

    async submitTagging() {
        if (!this.currentSession) return;
        const submitBtn = document.getElementById('submit-tagging-btn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                מייצר דוח פדגוגי בעברית...
            `;
        }

        const selectedRadio = document.querySelector('input[name="focus_child_radio"]:checked');
        const focusSpeakerId = selectedRadio ? selectedRadio.value : null;

        const speakerUpdates = [];
        let targetChildName = '';

        this.currentSession.speakers.forEach(spk => {
            const nameEl = document.getElementById(`spk-name-${spk.id}`);
            const roleEl = document.getElementById(`spk-role-${spk.id}`);
            const assignedName = nameEl ? nameEl.value.trim() : spk.assigned_name;
            const role = roleEl ? roleEl.value : spk.role;
            const isFocusChild = (spk.id === focusSpeakerId);

            if (isFocusChild) {
                targetChildName = assignedName;
            }

            speakerUpdates.push({
                speaker_id: spk.id,
                assigned_name: assignedName,
                role: role,
                is_child_in_focus: isFocusChild
            });
        });

        const focusPromptEl = document.getElementById('tagging-focus-prompt');
        const focusPrompt = focusPromptEl ? focusPromptEl.value.trim() : '';

        try {
            await API.configureSpeakers(this.currentSession.id, {
                speakers: speakerUpdates,
                focus_prompt: focusPrompt,
                target_child_name: targetChildName
            });

            // Transition to dashboard and start polling for completion
            app.showView('processing');
            app.pollSessionStatus(this.currentSession.id);
        } catch (err) {
            alert('שגיאה בשמירת התיוג: ' + err.message);
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'אשר תיוג והפק דוח פדגוגי';
            }
        }
    }

    extractSuggestions(context) {
        if (!context) return [];
        const suggestions = [];

        // 1. Target child
        const child = (context.target_child_name || '').trim();
        if (child) {
            suggestions.push({
                name: child,
                role: 'ילד/ה במוקד',
                is_focus: true,
                category: 'child',
                label: `👶 ${child}`,
                badge: 'ילד במוקד'
            });
        }

        // 2. Parents
        const parents = (context.parents_names || '').trim();
        if (parents) {
            const list = parents.replace(/;/g, ',').replace(/ ו/g, ',').split(',').map(s => s.trim()).filter(Boolean);
            list.forEach(p => {
                const clean = p.split('(')[0].trim();
                if (clean) {
                    suggestions.push({
                        name: clean,
                        role: 'הורה',
                        is_focus: false,
                        category: 'parent',
                        label: `👨‍👩‍👧 ${clean}`,
                        badge: 'הורה'
                    });
                }
            });
        }

        // 3. Staff
        const staff = (context.staff_names || '').trim();
        if (staff) {
            const list = staff.replace(/;/g, ',').split(',').map(s => s.trim()).filter(Boolean);
            list.forEach(s => {
                const role = s.includes('סייעת') ? 'סייעת' : (s.includes('גננת') ? 'גננת ראשית' : 'צוות חינוכי');
                const clean = s.split('(')[0].trim();
                if (clean) {
                    suggestions.push({
                        name: clean,
                        role: role,
                        is_focus: false,
                        category: 'staff',
                        label: `👩‍🏫 ${clean}`,
                        badge: role
                    });
                }
            });
        }

        // 4. Friends
        const friends = (context.friends_names || '').trim();
        if (friends) {
            const list = friends.replace(/;/g, ',').split(',').map(s => s.trim()).filter(Boolean);
            list.forEach(f => {
                const clean = f.split('(')[0].trim();
                if (clean) {
                    suggestions.push({
                        name: clean,
                        role: 'חבר/ה לגן',
                        is_focus: false,
                        category: 'friend',
                        label: `🎈 ${clean}`,
                        badge: 'חבר/ה לגן'
                    });
                }
            });
        }

        return suggestions;
    }

    applySuggestionToSpeaker(speakerId, name, role, isFocus) {
        const nameInput = document.getElementById(`spk-name-${speakerId}`);
        const roleSelect = document.getElementById(`spk-role-${speakerId}`);
        if (nameInput) nameInput.value = name;
        if (roleSelect) roleSelect.value = role;

        if (isFocus) {
            const radio = document.querySelector(`input[name="focus_child_radio"][value="${speakerId}"]`);
            if (radio) {
                radio.checked = true;
                this.onSelectFocusChild(speakerId);
            }
        }
    }

    applySuggestionToNextAvailable(name, role, isFocus) {
        if (!this.currentSession || !this.currentSession.speakers) return;

        // Find first speaker with placeholder name ("דובר X" or empty)
        let targetId = null;
        for (const spk of this.currentSession.speakers) {
            const nameInput = document.getElementById(`spk-name-${spk.id}`);
            const val = nameInput ? nameInput.value.trim() : '';
            if (val.startsWith('דובר') || !val) {
                targetId = spk.id;
                break;
            }
        }

        // If none has placeholder name, apply to first speaker
        if (!targetId && this.currentSession.speakers.length > 0) {
            targetId = this.currentSession.speakers[0].id;
        }

        if (targetId) {
            this.applySuggestionToSpeaker(targetId, name, role, isFocus);
            // Flash the card border to give visual feedback
            const card = document.getElementById(`speaker-card-${targetId}`);
            if (card) {
                card.classList.add('ring-4', 'ring-indigo-400');
                setTimeout(() => card.classList.remove('ring-4', 'ring-indigo-400'), 800);
            }
        }
    }
}

window.taggingController = new TaggingController();
