// Voice Tagging & Focus Configuration Screen Controller
class TaggingController {
    constructor() {
        this.currentSession = null;
        this.selectedChildSpeakerId = null;
        this.snippetAudios = {};
        this.activeSampleIndex = {};  // speakerId -> number
        this.currentAudio = null;
        this.currentPlayingKey = null; // `${speakerId}_${sampleIndex}`
    }

    renderTaggingScreen(session) {
        this.currentSession = session;
        this.stopAllAudio();
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
            this.activeSampleIndex[spk.id] = 0;

            const card = document.createElement('div');
            card.className = `p-4 sm:p-5 rounded-2xl border transition-all duration-200 ${
                spk.is_child_in_focus
                    ? 'border-emerald-500 bg-emerald-50/40 ring-2 ring-emerald-500/20 shadow-sm'
                    : 'border-slate-200 bg-white hover:border-indigo-300 shadow-2xs'
            }`;
            card.id = `speaker-card-${spk.id}`;

            const cardQuickChips = suggestions.length > 0 ? `
                <div class="mt-3 pt-2.5 border-t border-slate-100 flex flex-wrap items-center gap-1.5">
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
                <!-- Speaker Header -->
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-2xl flex items-center justify-center font-bold text-sm shrink-0 shadow-2xs ${
                            isDominant ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-700'
                        }">
                            ${idx + 1}
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="font-bold text-slate-900 text-sm sm:text-base">${spk.diarization_tag}</span>
                                ${isDominant ? '<span class="text-xs bg-indigo-100 text-indigo-700 px-2.5 py-0.5 rounded-full font-bold">הדובר הדומיננטי</span>' : ''}
                            </div>
                            <span class="text-xs text-slate-500">
                                סה"כ דיבור: <strong>${Math.round(spk.total_speech_seconds)}</strong> שנ' (~${pct}%) | <strong>${spk.utterance_count}</strong> מקטעים
                            </span>
                        </div>
                    </div>
                </div>

                <!-- Multi-Sample Review Section -->
                <div id="speaker-samples-section-${spk.id}" class="mb-4">
                    ${this.renderSpeakerSamplesHTML(spk)}
                </div>

                <!-- Input Controls -->
                <div class="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
                    <!-- Assigned Name -->
                    <div class="sm:col-span-5">
                        <label class="block text-xs font-bold text-slate-700 mb-1">שם או כינוי</label>
                        <input type="text" 
                               id="spk-name-${spk.id}"
                               value="${spk.assigned_name || (idx === 0 ? 'גננת מיכל' : (idx === 1 ? 'סייעת' : 'ילד/ה'))}"
                               placeholder="לדוגמה: הגננת מיכל / הבן שלי איתי"
                               class="w-full text-sm px-3 py-2 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white font-medium" />
                    </div>

                    <!-- Role Dropdown -->
                    <div class="sm:col-span-4">
                        <label class="block text-xs font-bold text-slate-700 mb-1">תפקיד / קטגוריה</label>
                        <select id="spk-role-${spk.id}"
                                class="w-full text-sm px-3 py-2 border border-slate-300 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white font-medium">
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
                        <label class="relative flex items-center gap-2 cursor-pointer p-2 rounded-xl hover:bg-slate-50 w-full sm:w-auto border border-transparent hover:border-slate-200 transition-colors">
                            <input type="radio" 
                                   name="focus_child_radio" 
                                   value="${spk.id}"
                                   ${spk.is_child_in_focus || idx === 2 ? 'checked' : ''}
                                   onchange="taggingController.onSelectFocusChild('${spk.id}')"
                                   class="w-4 h-4 text-emerald-600 focus:ring-emerald-500 border-slate-300">
                            <span class="text-xs font-bold text-emerald-800">
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

        // Asynchronously check if samples were missing and fetch them
        const hasSamples = session.speakers && session.speakers.some(s => s.samples && s.samples.length > 0);
        if (!hasSamples && session.speakers && session.speakers.length > 0) {
            this.fetchAndInjectSamples(session.id);
        }
    }

    renderSpeakerSamplesHTML(spk) {
        const samples = spk.samples || [];
        if (!samples || samples.length === 0) {
            return `
                <div class="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-200">
                    <span class="text-xs text-slate-500 font-medium">דגימת קול ברירת מחדל:</span>
                    <button type="button" 
                            onclick="taggingController.playSnippet('${spk.session_id}', '${spk.diarization_tag}', this)"
                            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-white text-indigo-700 hover:bg-indigo-50 border border-slate-200 transition-colors shadow-2xs">
                        <svg class="w-3.5 h-3.5 play-icon" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"></path>
                        </svg>
                        <span class="btn-text">האזן לדגימה</span>
                    </button>
                </div>
            `;
        }

        const activeIdx = this.activeSampleIndex[spk.id] || 0;
        const activeSample = samples[activeIdx] || samples[0];

        return `
            <div class="bg-gradient-to-r from-slate-50 via-indigo-50/20 to-slate-50 rounded-2xl border border-slate-200/90 p-3 sm:p-3.5 shadow-2xs">
                <!-- Top Tabs & Title -->
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2.5 pb-2 border-b border-slate-200/60">
                    <div class="flex items-center gap-1.5">
                        <span class="text-xs font-black text-slate-800">🎙️ דגימות קול להאזנה (${samples.length}):</span>
                        <span class="text-[10px] text-slate-500 hidden sm:inline">האזן לקטעים שונים ביום לזיהוי ודאי</span>
                    </div>

                    <!-- Sample Selection Chips -->
                    <div class="flex flex-wrap items-center gap-1.5" id="sample-tabs-${spk.id}">
                        ${samples.map((smp, sIdx) => `
                            <button type="button"
                                    id="sample-tab-${spk.id}-${sIdx}"
                                    onclick="taggingController.selectSample('${spk.id}', ${sIdx})"
                                    title="${smp.text.replace(/"/g, '&quot;')}"
                                    class="px-2.5 py-1 text-[11px] rounded-xl font-bold transition-all border flex items-center gap-1.5 cursor-pointer ${
                                        sIdx === activeIdx
                                            ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
                                            : 'bg-white hover:bg-slate-100 text-slate-700 border-slate-200 shadow-2xs'
                                    }">
                                <span>קטע ${sIdx + 1}</span>
                                <span class="text-[10px] opacity-80 font-mono">(${smp.formatted_time})</span>
                                ${smp.is_isolated ? '<span class="text-[9px] bg-emerald-500 text-white px-1.5 py-0.5 rounded-full font-normal shadow-2xs">ללא חפיפה</span>' : ''}
                            </button>
                        `).join('')}
                    </div>
                </div>

                <!-- Active Sample Transcript Quote -->
                <div class="bg-white rounded-xl p-3 border border-slate-200/80 mb-2.5 shadow-2xs">
                    <div class="flex items-start gap-2.5">
                        <span class="text-indigo-600 text-base leading-none select-none">💬</span>
                        <div class="flex-1 min-w-0">
                            <p class="text-xs sm:text-sm text-slate-800 font-semibold leading-relaxed" id="sample-quote-${spk.id}">
                                "${activeSample.text}"
                            </p>
                            <div class="mt-1.5 flex flex-wrap items-center gap-3 text-[10px] text-slate-500">
                                <span id="sample-time-meta-${spk.id}">
                                    זמן בהקלטה: <strong class="font-mono text-slate-700">${activeSample.formatted_time}</strong> | משך: <strong class="text-slate-700">${activeSample.duration} שנ'</strong>
                                </span>
                                <span id="sample-iso-meta-${spk.id}" class="${activeSample.is_isolated ? 'text-emerald-700 font-bold' : 'text-slate-400 font-medium'}">
                                    ${activeSample.is_isolated ? '✓ קטע מבודד (ללא קולות רקע במקביל)' : '• שיחה ברצף'}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Controls Bar -->
                <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="flex items-center gap-1.5">
                        <!-- Play/Pause Button -->
                        <button type="button"
                                id="sample-play-btn-${spk.id}"
                                onclick="taggingController.togglePlayActiveSample('${spk.id}')"
                                class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-2xs transition-all cursor-pointer">
                            <svg class="w-3.5 h-3.5 play-icon" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"></path>
                            </svg>
                            <span class="btn-text">האזן לקטע ${activeIdx + 1} (${activeSample.duration} שנ')</span>
                        </button>

                        <!-- Prev Clip -->
                        <button type="button"
                                onclick="taggingController.prevSample('${spk.id}')"
                                title="עבור לקטע הקודם של דובר זה"
                                class="p-1.5 rounded-xl bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs transition-colors shadow-2xs cursor-pointer">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"></path>
                            </svg>
                        </button>

                        <!-- Next Clip -->
                        <button type="button"
                                onclick="taggingController.nextSample('${spk.id}')"
                                title="עבור לקטע הבא של דובר זה"
                                class="p-1.5 rounded-xl bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs transition-colors shadow-2xs cursor-pointer">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M15 19l-7-7 7-7"></path>
                            </svg>
                        </button>
                    </div>

                    <!-- Seek Full Audio Context Button -->
                    <button type="button"
                            id="sample-seek-btn-${spk.id}"
                            onclick="taggingController.seekInFullPlayer(${activeSample.start_time})"
                            title="קפוץ בנגן ההקלטה הראשי לרגע זה (כולל ההקשר שלפני ואחרי)"
                            class="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-bold text-slate-600 hover:text-indigo-700 bg-white hover:bg-indigo-50 border border-slate-200 rounded-xl transition-colors shadow-2xs cursor-pointer">
                        <svg class="w-3.5 h-3.5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path>
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                        </svg>
                        <span>האזן בהקשר המלא בנגן (${activeSample.formatted_time})</span>
                    </button>
                </div>
            </div>
        `;
    }

    async fetchAndInjectSamples(sessionId) {
        try {
            const samplesMap = await API.getAllSpeakerSamples(sessionId);
            if (!samplesMap || !this.currentSession) return;

            this.currentSession.speakers.forEach(spk => {
                if (samplesMap[spk.id] && samplesMap[spk.id].length > 0) {
                    spk.samples = samplesMap[spk.id];
                    const section = document.getElementById(`speaker-samples-section-${spk.id}`);
                    if (section) {
                        section.innerHTML = this.renderSpeakerSamplesHTML(spk);
                    }
                }
            });
        } catch (e) {
            console.warn('[TaggingController] Could not fetch speaker samples in background:', e);
        }
    }

    selectSample(speakerId, sampleIndex, autoPlay = false) {
        this.activeSampleIndex[speakerId] = sampleIndex;
        const spk = (this.currentSession?.speakers || []).find(s => s.id === speakerId);
        if (!spk || !spk.samples || !spk.samples[sampleIndex]) return;

        const sample = spk.samples[sampleIndex];

        // Update tabs styling
        spk.samples.forEach((_, idx) => {
            const tabEl = document.getElementById(`sample-tab-${speakerId}-${idx}`);
            if (tabEl) {
                if (idx === sampleIndex) {
                    tabEl.className = 'px-2.5 py-1 text-[11px] rounded-xl font-bold transition-all border flex items-center gap-1.5 cursor-pointer bg-indigo-600 text-white border-indigo-600 shadow-2xs';
                } else {
                    tabEl.className = 'px-2.5 py-1 text-[11px] rounded-xl font-bold transition-all border flex items-center gap-1.5 cursor-pointer bg-white hover:bg-slate-100 text-slate-700 border-slate-200 shadow-2xs';
                }
            }
        });

        // Update quote text
        const quoteEl = document.getElementById(`sample-quote-${speakerId}`);
        if (quoteEl) quoteEl.textContent = `"${sample.text}"`;

        // Update time metadata
        const timeMetaEl = document.getElementById(`sample-time-meta-${speakerId}`);
        if (timeMetaEl) {
            timeMetaEl.innerHTML = `זמן בהקלטה: <strong class="font-mono text-slate-700">${sample.formatted_time}</strong> | משך: <strong class="text-slate-700">${sample.duration} שנ'</strong>`;
        }

        // Update isolated badge
        const isoMetaEl = document.getElementById(`sample-iso-meta-${speakerId}`);
        if (isoMetaEl) {
            isoMetaEl.className = sample.is_isolated ? 'text-emerald-700 font-bold' : 'text-slate-400 font-medium';
            isoMetaEl.textContent = sample.is_isolated ? '✓ קטע מבודד (ללא קולות רקע במקביל)' : '• שיחה ברצף';
        }

        // Update play button
        const playBtn = document.getElementById(`sample-play-btn-${speakerId}`);
        if (playBtn) {
            const isPlayingThis = (this.currentPlayingKey === `${speakerId}_${sampleIndex}` && this.currentAudio && !this.currentAudio.paused);
            playBtn.querySelector('.btn-text').textContent = isPlayingThis
                ? `מנגן קטע ${sampleIndex + 1} (עצור)`
                : `האזן לקטע ${sampleIndex + 1} (${sample.duration} שנ')`;
            if (isPlayingThis) {
                playBtn.classList.remove('bg-indigo-600', 'hover:bg-indigo-700');
                playBtn.classList.add('bg-amber-600', 'hover:bg-amber-700');
            } else {
                playBtn.classList.remove('bg-amber-600', 'hover:bg-amber-700');
                playBtn.classList.add('bg-indigo-600', 'hover:bg-indigo-700');
            }
        }

        // Update seek button
        const seekBtn = document.getElementById(`sample-seek-btn-${speakerId}`);
        if (seekBtn) {
            seekBtn.setAttribute('onclick', `taggingController.seekInFullPlayer(${sample.start_time})`);
            const labelSpan = seekBtn.querySelector('span');
            if (labelSpan) labelSpan.textContent = `האזן בהקשר המלא בנגן (${sample.formatted_time})`;
        }

        // If audio was already playing for this speaker or autoPlay is requested, play new clip immediately
        if (autoPlay || (this.currentPlayingKey && this.currentPlayingKey.startsWith(`${speakerId}_`))) {
            this.togglePlayActiveSample(speakerId, true);
        }
    }

    togglePlayActiveSample(speakerId, forcePlay = false) {
        const spk = (this.currentSession?.speakers || []).find(s => s.id === speakerId);
        if (!spk || !spk.samples) return;

        const activeIdx = this.activeSampleIndex[speakerId] || 0;
        const sample = spk.samples[activeIdx];
        if (!sample) return;

        const key = `${speakerId}_${activeIdx}`;
        const btn = document.getElementById(`sample-play-btn-${speakerId}`);

        // If currently playing this sample and not forcing play, pause it
        if (!forcePlay && this.currentPlayingKey === key && this.currentAudio && !this.currentAudio.paused) {
            this.currentAudio.pause();
            this.currentAudio = null;
            this.currentPlayingKey = null;
            if (btn) {
                btn.querySelector('.btn-text').textContent = `האזן לקטע ${activeIdx + 1} (${sample.duration} שנ')`;
                btn.classList.remove('bg-amber-600', 'hover:bg-amber-700');
                btn.classList.add('bg-indigo-600', 'hover:bg-indigo-700');
            }
            return;
        }

        // Stop all other audio
        this.stopAllAudio();

        if (btn) {
            btn.querySelector('.btn-text').textContent = `טוען קטע...`;
        }

        const audio = new Audio(sample.audio_url);
        this.currentAudio = audio;
        this.currentPlayingKey = key;

        audio.addEventListener('playing', () => {
            if (btn && this.currentPlayingKey === key) {
                btn.querySelector('.btn-text').textContent = `מנגן קטע ${activeIdx + 1} (עצור)`;
                btn.classList.remove('bg-indigo-600', 'hover:bg-indigo-700');
                btn.classList.add('bg-amber-600', 'hover:bg-amber-700');
            }
        });

        audio.addEventListener('ended', () => {
            if (btn) {
                btn.querySelector('.btn-text').textContent = `האזן לקטע ${activeIdx + 1} (${sample.duration} שנ')`;
                btn.classList.remove('bg-amber-600', 'hover:bg-amber-700');
                btn.classList.add('bg-indigo-600', 'hover:bg-indigo-700');
            }
            this.currentAudio = null;
            this.currentPlayingKey = null;
        });

        audio.addEventListener('error', (e) => {
            console.warn('[TaggingController] Audio playback error:', e);
            if (btn) {
                btn.querySelector('.btn-text').textContent = `שגיאה בהשמעה - לחץ שוב`;
                btn.classList.remove('bg-amber-600', 'hover:bg-amber-700');
                btn.classList.add('bg-rose-600', 'hover:bg-rose-700');
                setTimeout(() => {
                    if (btn) {
                        btn.querySelector('.btn-text').textContent = `האזן לקטע ${activeIdx + 1} (${sample.duration} שנ')`;
                        btn.classList.remove('bg-rose-600', 'hover:bg-rose-700');
                        btn.classList.add('bg-indigo-600', 'hover:bg-indigo-700');
                    }
                }, 2500);
            }
            this.currentAudio = null;
            this.currentPlayingKey = null;
        });

        audio.play().catch(err => {
            console.warn('[TaggingController] audio.play() was prevented:', err);
        });
    }

    nextSample(speakerId) {
        const spk = (this.currentSession?.speakers || []).find(s => s.id === speakerId);
        if (!spk || !spk.samples || spk.samples.length <= 1) return;
        const cur = this.activeSampleIndex[speakerId] || 0;
        const nextIdx = (cur + 1) % spk.samples.length;
        const wasPlaying = (this.currentPlayingKey && this.currentPlayingKey.startsWith(`${speakerId}_`));
        this.selectSample(speakerId, nextIdx, wasPlaying);
    }

    prevSample(speakerId) {
        const spk = (this.currentSession?.speakers || []).find(s => s.id === speakerId);
        if (!spk || !spk.samples || spk.samples.length <= 1) return;
        const cur = this.activeSampleIndex[speakerId] || 0;
        const prevIdx = (cur - 1 + spk.samples.length) % spk.samples.length;
        const wasPlaying = (this.currentPlayingKey && this.currentPlayingKey.startsWith(`${speakerId}_`));
        this.selectSample(speakerId, prevIdx, wasPlaying);
    }

    seekInFullPlayer(startTime) {
        if (window.audioPlayer && this.currentSession) {
            // Stop isolated snippet
            this.stopAllAudio();

            if (!audioPlayer.audio.src || !audioPlayer.audio.src.includes(this.currentSession.id)) {
                audioPlayer.loadAudio(this.currentSession.id, this.currentSession.duration_seconds || 0);
            }
            // Seek 1.5 seconds before utterance for natural lead-in
            const seekTime = Math.max(0, startTime - 1.5);
            audioPlayer.seekTo(seekTime, true);
            const bar = document.getElementById('audio-player-bar');
            if (bar) {
                bar.classList.remove('hidden');
                bar.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }
    }

    stopAllAudio() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio = null;
        }
        this.currentPlayingKey = null;

        Object.values(this.snippetAudios).forEach(a => a.pause());
        this.snippetAudios = {};

        // Reset all play buttons on cards
        (this.currentSession?.speakers || []).forEach(spk => {
            const btn = document.getElementById(`sample-play-btn-${spk.id}`);
            if (btn) {
                const activeIdx = this.activeSampleIndex[spk.id] || 0;
                const sample = spk.samples ? spk.samples[activeIdx] : null;
                const dur = sample ? sample.duration : 6;
                btn.querySelector('.btn-text').textContent = `האזן לקטע ${activeIdx + 1} (${dur} שנ')`;
                btn.classList.remove('bg-amber-600', 'hover:bg-amber-700', 'bg-rose-600', 'hover:bg-rose-700');
                btn.classList.add('bg-indigo-600', 'hover:bg-indigo-700');
            }
        });
        document.querySelectorAll('.btn-text').forEach(el => {
            if (el.textContent.includes('מנגן')) el.textContent = 'האזן לדגימה';
        });
    }

    playSnippet(sessionId, speakerTag, btn) {
        const key = `${sessionId}_${speakerTag}`;
        if (this.snippetAudios[key] && !this.snippetAudios[key].paused) {
            this.snippetAudios[key].pause();
            btn.querySelector('.btn-text').textContent = 'האזן לדגימה';
            return;
        }

        // Stop all other snippets
        this.stopAllAudio();

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
        this.stopAllAudio();

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
