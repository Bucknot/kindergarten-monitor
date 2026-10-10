// Main Application Controller
class KindergartenMonitorApp {
    constructor() {
        this.currentSessionId = null;
        this.currentSession = null;
        this.transcriptSegments = [];
        this.transcriptPage = 1;
        this.transcriptPageSize = 250;
        this.transcriptTotalPages = 1;
        this.transcriptTotalCount = 0;
        this.selectedHour = null;
        this.pollInterval = null;
        this.activeSegmentId = null;

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }

    async init() {
        this.loadSavedSettings();
        this.attachFormListeners();
        this.setupAudioSync();
        await this.loadRecentSessions();

        if (window.chatController) {
            chatController.init();
        }

        // Check URL parameter for session id
        const urlParams = new URLSearchParams(window.location.search);
        const sid = urlParams.get('session');
        if (sid) {
            this.openSession(sid);
        } else {
            this.showView('welcome');
        }
    }

    loadSavedSettings() {
        // Load Gladia key
        const savedGladiaKey = localStorage.getItem('gladia_api_key') || '';
        const gladiaInput = document.getElementById('cfg-gladia-key');
        if (gladiaInput && savedGladiaKey) gladiaInput.value = savedGladiaKey;

        // Load OpenRouter key & model
        const savedORKey = localStorage.getItem('openrouter_api_key') || '';
        const orInput = document.getElementById('cfg-openrouter-key');
        if (orInput && savedORKey) orInput.value = savedORKey;

        const savedORModel = localStorage.getItem('openrouter_model') || 'google/gemini-2.5-flash';
        const orModelInput = document.getElementById('cfg-openrouter-model');
        if (orModelInput) orModelInput.value = savedORModel;

        // Load OpenRouter STT Model (respect whatever the user saved)
        const savedORSTTModel = localStorage.getItem('openrouter_stt_model') || 'elevenlabs/scribe-v2';
        const orSTTModelInput = document.getElementById('cfg-openrouter-stt-model');
        if (orSTTModelInput) orSTTModelInput.value = savedORSTTModel;

        // Load Audio Listener model
        const savedAudioModel = localStorage.getItem('audio_llm_model') || 'google/gemini-2.5-flash';
        const audioModelInput = document.getElementById('cfg-audio-llm-model');
        if (audioModelInput) audioModelInput.value = savedAudioModel;

        // Load OpenAI STT settings
        const savedOpenAIKey = localStorage.getItem('openai_stt_api_key') || '';
        const openaiKeyInput = document.getElementById('cfg-openai-stt-key');
        if (openaiKeyInput && savedOpenAIKey) openaiKeyInput.value = savedOpenAIKey;

        const savedOpenAIBaseUrl = localStorage.getItem('openai_stt_base_url') || 'https://api.groq.com/openai/v1';
        const openaiBaseUrlInput = document.getElementById('cfg-openai-stt-base-url');
        if (openaiBaseUrlInput) openaiBaseUrlInput.value = savedOpenAIBaseUrl;

        const savedOpenAIModel = localStorage.getItem('openai_stt_model') || 'whisper-large-v3';
        const openaiModelInput = document.getElementById('cfg-openai-stt-model');
        if (openaiModelInput) openaiModelInput.value = savedOpenAIModel;

        // Load STT provider
        const savedSTTProvider = localStorage.getItem('stt_provider') || 'gladia';
        const sttSelect = document.getElementById('stt-provider-select');
        if (sttSelect) {
            sttSelect.value = savedSTTProvider;
            this.onSTTProviderChange();
        }

        // Load file path and child name if saved
        const savedPath = localStorage.getItem('local_file_path');
        const pathInput = document.getElementById('local-file-path-input');
        if (savedPath && pathInput && !pathInput.value) pathInput.value = savedPath;

        const savedChild = localStorage.getItem('local_child');
        const childInput = document.getElementById('local-child-input');
        if (savedChild && childInput && !childInput.value) childInput.value = savedChild;

        const savedPrompt = localStorage.getItem('local_prompt');
        const promptInput = document.getElementById('local-prompt-input');
        if (savedPrompt && promptInput && !promptInput.value) promptInput.value = savedPrompt;

        // Load Kindergarten Profile
        this.loadKindergartenProfile();

        // Auto-save listeners
        [
            gladiaInput, orInput, orModelInput, orSTTModelInput, audioModelInput,
            openaiKeyInput, openaiBaseUrlInput, openaiModelInput,
            sttSelect, pathInput, childInput, promptInput
        ].forEach(el => {
            if (el) {
                el.addEventListener('input', () => this.saveSettings());
                el.addEventListener('change', () => this.saveSettings());
            }
        });
    }

    loadKindergartenProfile() {
        try {
            const raw = localStorage.getItem('kindergarten_profile');
            if (raw) {
                const profile = JSON.parse(raw);
                if (profile.target_child_name) {
                    const ctxChild = document.getElementById('ctx-child-name');
                    if (ctxChild) ctxChild.value = profile.target_child_name;
                    const localChild = document.getElementById('local-child-input');
                    if (localChild && !localChild.value) localChild.value = profile.target_child_name;
                }
                if (profile.parents_names) {
                    const el = document.getElementById('ctx-parents-names');
                    if (el) el.value = profile.parents_names;
                }
                if (profile.kindergarten_name) {
                    const el = document.getElementById('ctx-kindergarten-name');
                    if (el) el.value = profile.kindergarten_name;
                }
                if (profile.staff_names) {
                    const el = document.getElementById('ctx-staff-names');
                    if (el) el.value = profile.staff_names;
                }
                if (profile.friends_names) {
                    const el = document.getElementById('ctx-friends-names');
                    if (el) el.value = profile.friends_names;
                }
                if (profile.key_vocabulary) {
                    const el = document.getElementById('ctx-keywords');
                    if (el) el.value = profile.key_vocabulary;
                }
                if (profile.custom_notes) {
                    const el = document.getElementById('ctx-custom-notes');
                    if (el) el.value = profile.custom_notes;
                }
            }
        } catch (e) {
            console.warn('[App] Error loading kindergarten profile:', e);
        }

        // Setup save button and sync listeners
        const saveBtn = document.getElementById('btn-save-profile');
        if (saveBtn) {
            saveBtn.onclick = () => this.saveKindergartenProfile(true);
        }

        const ctxChild = document.getElementById('ctx-child-name');
        const localChild = document.getElementById('local-child-input');
        if (ctxChild && localChild) {
            ctxChild.addEventListener('input', () => {
                localChild.value = ctxChild.value;
                this.saveKindergartenProfile(false);
            });
            localChild.addEventListener('input', () => {
                ctxChild.value = localChild.value;
                this.saveKindergartenProfile(false);
            });
        }

        ['ctx-parents-names', 'ctx-kindergarten-name', 'ctx-staff-names', 'ctx-friends-names', 'ctx-keywords', 'ctx-custom-notes'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', () => this.saveKindergartenProfile(false));
                el.addEventListener('change', () => this.saveKindergartenProfile(false));
            }
        });
    }

    saveKindergartenProfile(showFeedback = false) {
        const profile = this.getKindergartenProfile();
        localStorage.setItem('kindergarten_profile', JSON.stringify(profile));
        if (profile.target_child_name) {
            localStorage.setItem('local_child', profile.target_child_name);
        }

        if (showFeedback) {
            const badge = document.getElementById('profile-saved-badge');
            if (badge) {
                badge.classList.remove('hidden');
                setTimeout(() => badge.classList.add('hidden'), 2500);
            }
        }
    }

    getKindergartenProfile() {
        const child = document.getElementById('ctx-child-name')?.value.trim() || document.getElementById('local-child-input')?.value.trim() || '';
        const parents = document.getElementById('ctx-parents-names')?.value.trim() || '';
        const kindergarten = document.getElementById('ctx-kindergarten-name')?.value.trim() || '';
        const staff = document.getElementById('ctx-staff-names')?.value.trim() || '';
        const friends = document.getElementById('ctx-friends-names')?.value.trim() || '';
        const keywords = document.getElementById('ctx-keywords')?.value.trim() || '';
        const customNotes = document.getElementById('ctx-custom-notes')?.value.trim() || '';

        return {
            target_child_name: child,
            parents_names: parents,
            kindergarten_name: kindergarten,
            staff_names: staff,
            friends_names: friends,
            key_vocabulary: keywords,
            custom_notes: customNotes
        };
    }

    saveSettings() {
        const gladiaKey = document.getElementById('cfg-gladia-key')?.value.trim() || '';
        const orKey = document.getElementById('cfg-openrouter-key')?.value.trim() || '';
        const orModel = document.getElementById('cfg-openrouter-model')?.value.trim() || 'google/gemini-2.5-flash';
        const orSTTModel = document.getElementById('cfg-openrouter-stt-model')?.value.trim() || 'elevenlabs/scribe-v2';
        const audioModel = document.getElementById('cfg-audio-llm-model')?.value.trim() || 'google/gemini-2.5-flash';
        const openaiKey = document.getElementById('cfg-openai-stt-key')?.value.trim() || '';
        const openaiBaseUrl = document.getElementById('cfg-openai-stt-base-url')?.value.trim() || '';
        const openaiModel = document.getElementById('cfg-openai-stt-model')?.value.trim() || '';
        const sttProvider = document.getElementById('stt-provider-select')?.value || 'gladia';
        const filePath = document.getElementById('local-file-path-input')?.value.trim() || '';
        const childName = document.getElementById('local-child-input')?.value.trim() || '';
        const promptText = document.getElementById('local-prompt-input')?.value.trim() || '';

        if (gladiaKey) localStorage.setItem('gladia_api_key', gladiaKey);
        if (orKey) localStorage.setItem('openrouter_api_key', orKey);
        if (orModel) localStorage.setItem('openrouter_model', orModel);
        if (orSTTModel) localStorage.setItem('openrouter_stt_model', orSTTModel);
        if (audioModel) localStorage.setItem('audio_llm_model', audioModel);
        if (openaiKey) localStorage.setItem('openai_stt_api_key', openaiKey);
        if (openaiBaseUrl) localStorage.setItem('openai_stt_base_url', openaiBaseUrl);
        if (openaiModel) localStorage.setItem('openai_stt_model', openaiModel);
        if (sttProvider) localStorage.setItem('stt_provider', sttProvider);
        if (filePath) localStorage.setItem('local_file_path', filePath);
        if (childName) localStorage.setItem('local_child', childName);
        if (promptText) localStorage.setItem('local_prompt', promptText);
    }

    onSTTProviderChange() {
        const provider = document.getElementById('stt-provider-select')?.value || 'gladia';
        const gladiaGroup = document.getElementById('gladia-key-group');
        const deepgramGroup = document.getElementById('deepgram-key-group');
        const openaiGroup = document.getElementById('openai-key-group');
        const openrouterGroup = document.getElementById('openrouter-stt-group');

        if (gladiaGroup) {
            gladiaGroup.classList.toggle('hidden', provider !== 'gladia');
        }

        if (deepgramGroup) {
            deepgramGroup.classList.toggle('hidden', provider !== 'deepgram');
        }

        if (openaiGroup) {
            openaiGroup.classList.toggle('hidden', provider !== 'openai_compatible');
        }

        if (openrouterGroup) {
            openrouterGroup.classList.toggle('hidden', provider !== 'openrouter');
        }

        this.saveSettings();
    }

    showView(viewName) {
        ['welcome', 'processing', 'tagging', 'dashboard'].forEach(v => {
            const el = document.getElementById(`view-${v}`);
            if (el) {
                if (v === viewName) {
                    el.classList.remove('hidden');
                } else {
                    el.classList.add('hidden');
                }
            }
        });
        if (viewName === 'welcome') {
            this.loadSavedSettings();
        }
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    attachFormListeners() {
        // Path submission form
        const pathForm = document.getElementById('local-path-form');
        if (pathForm) {
            pathForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.handleLocalPathSubmit();
            });
        }

        // Upload form
        const uploadForm = document.getElementById('upload-form');
        if (uploadForm) {
            uploadForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.handleUploadSubmit();
            });
        }

        // Sample loader button
        const sampleBtn = document.getElementById('load-sample-btn');
        if (sampleBtn) {
            sampleBtn.addEventListener('click', () => {
                const input = document.getElementById('local-file-path-input');
                if (input) {
                    input.value = 'storage/sample.mp3';
                    const title = document.getElementById('local-title-input');
                    if (title) title.value = 'הקלטת יום בגן - הדגמה';
                    const child = document.getElementById('local-child-input');
                    if (child) child.value = 'איתמר';
                    const prompt = document.getElementById('local-prompt-input');
                    if (prompt) prompt.value = 'בדוק התנהלות בארוחות ויחס הצוות בזמן בכי בחצר';
                }
            });
        }

        // Transcript search & filters
        const searchInput = document.getElementById('transcript-search-input');
        if (searchInput) {
            let debounceTimer;
            searchInput.addEventListener('input', () => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    this.transcriptPage = 1;
                    this.reloadTranscript(1, false);
                }, 300);
            });
        }

        const speakerFilter = document.getElementById('transcript-speaker-filter');
        if (speakerFilter) {
            speakerFilter.addEventListener('change', () => {
                this.transcriptPage = 1;
                this.reloadTranscript(1, false);
            });
        }

        const flaggedFilter = document.getElementById('transcript-flagged-filter');
        if (flaggedFilter) {
            flaggedFilter.addEventListener('change', () => {
                this.transcriptPage = 1;
                this.reloadTranscript(1, false);
            });
        }
    }

    async handleLocalPathSubmit() {
        console.log('[App] handleLocalPathSubmit called');
        if (this.isSubmitting) return;

        const pathInput = document.getElementById('local-file-path-input');
        const titleInput = document.getElementById('local-title-input');
        const childInput = document.getElementById('local-child-input');
        const promptInput = document.getElementById('local-prompt-input');
        const providerSelect = document.getElementById('stt-provider-select');

        if (!pathInput || !pathInput.value.trim()) {
            alert('אנא הזן נתיב תקין לקובץ ההקלטה במחשב');
            return;
        }

        const submitBtn = document.getElementById('submit-path-btn');
        const originalBtnHtml = submitBtn ? submitBtn.innerHTML : '';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline-block" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                <span>מתחיל ניתוח...</span>
            `;
        }

        this.isSubmitting = true;
        this.saveSettings();
        const gladiaKey = document.getElementById('cfg-gladia-key')?.value.trim();
        const deepgramKey = document.getElementById('cfg-deepgram-key')?.value.trim();
        const openaiKey = document.getElementById('cfg-openai-stt-key')?.value.trim();
        const openaiBaseUrl = document.getElementById('cfg-openai-stt-base-url')?.value.trim();
        const openaiModel = document.getElementById('cfg-openai-stt-model')?.value.trim();
        const orKey = document.getElementById('cfg-openrouter-key')?.value.trim();
        const orModel = document.getElementById('cfg-openrouter-model')?.value.trim();
        const orSTTModel = document.getElementById('cfg-openrouter-stt-model')?.value.trim();
        const audioModel = document.getElementById('cfg-audio-llm-model')?.value.trim();

        const profile = this.getKindergartenProfile();
        const effectiveChild = (childInput && childInput.value.trim()) ? childInput.value.trim() : (profile.target_child_name || null);

        try {
            console.log('[App] Sending createSessionFromPath request with context_metadata...', profile);
            const session = await API.createSessionFromPath({
                local_file_path: pathInput.value.trim(),
                title: titleInput ? titleInput.value.trim() : 'הקלטת יום בגן',
                target_child_name: effectiveChild,
                focus_prompt: promptInput ? promptInput.value.trim() : null,
                context_metadata: profile,
                stt_provider: providerSelect ? providerSelect.value : 'gladia',
                gladia_api_key: gladiaKey || null,
                deepgram_api_key: deepgramKey || null,
                openai_stt_api_key: openaiKey || null,
                openai_stt_base_url: openaiBaseUrl || null,
                openai_stt_model: openaiModel || null,
                openrouter_api_key: orKey || null,
                openrouter_model: orModel || null,
                openrouter_stt_model: orSTTModel || null,
                audio_llm_model: audioModel || null
            });

            console.log('[App] Session created successfully:', session);
            this.currentSessionId = session.id;
            this.showView('processing');
            this.pollSessionStatus(session.id);
        } catch (err) {
            console.error('[App] Error creating session:', err);
            alert('שגיאה ביצירת הפעלה: ' + err.message);
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnHtml;
            }
        } finally {
            this.isSubmitting = false;
        }
    }

    async handleUploadSubmit() {
        console.log('[App] handleUploadSubmit called');
        if (this.isSubmitting) return;

        const fileInput = document.getElementById('file-upload-input');
        const titleInput = document.getElementById('upload-title-input');
        const childInput = document.getElementById('upload-child-input');
        const promptInput = document.getElementById('upload-prompt-input');

        if (!fileInput || !fileInput.files.length) {
            alert('אנא בחר קובץ להעלאה');
            return;
        }

        const submitBtn = document.getElementById('submit-upload-btn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'מעלה קובץ...';
        }

        this.isSubmitting = true;
        this.saveSettings();
        const gladiaKey = document.getElementById('cfg-gladia-key')?.value.trim();
        const deepgramKey = document.getElementById('cfg-deepgram-key')?.value.trim();
        const openaiKey = document.getElementById('cfg-openai-stt-key')?.value.trim();
        const openaiBaseUrl = document.getElementById('cfg-openai-stt-base-url')?.value.trim();
        const openaiModel = document.getElementById('cfg-openai-stt-model')?.value.trim();
        const orKey = document.getElementById('cfg-openrouter-key')?.value.trim();
        const orModel = document.getElementById('cfg-openrouter-model')?.value.trim();
        const orSTTModel = document.getElementById('cfg-openrouter-stt-model')?.value.trim();
        const audioModel = document.getElementById('cfg-audio-llm-model')?.value.trim();
        const providerSelect = document.getElementById('upload-stt-provider-select') || document.getElementById('stt-provider-select');

        const profile = this.getKindergartenProfile();
        const effectiveChild = (childInput && childInput.value.trim()) ? childInput.value.trim() : (profile.target_child_name || '');

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        if (titleInput && titleInput.value.trim()) formData.append('title', titleInput.value.trim());
        if (effectiveChild) formData.append('target_child_name', effectiveChild);
        if (promptInput && promptInput.value.trim()) formData.append('focus_prompt', promptInput.value.trim());
        formData.append('context_metadata', JSON.stringify(profile));
        if (providerSelect) formData.append('stt_provider', providerSelect.value);
        if (gladiaKey) formData.append('gladia_api_key', gladiaKey);
        if (deepgramKey) formData.append('deepgram_api_key', deepgramKey);
        if (openaiKey) formData.append('openai_stt_api_key', openaiKey);
        if (openaiBaseUrl) formData.append('openai_stt_base_url', openaiBaseUrl);
        if (openaiModel) formData.append('openai_stt_model', openaiModel);
        if (orKey) formData.append('openrouter_api_key', orKey);
        if (orModel) formData.append('openrouter_model', orModel);
        if (orSTTModel) formData.append('openrouter_stt_model', orSTTModel);
        if (audioModel) formData.append('audio_llm_model', audioModel);

        try {
            console.log('[App] Sending uploadSession request...');
            const session = await API.uploadSession(formData);
            console.log('[App] Upload created session:', session);
            this.currentSessionId = session.id;
            this.showView('processing');
            this.pollSessionStatus(session.id);
        } catch (err) {
            console.error('[App] Error uploading session:', err);
            alert('שגיאה בהעלאת קובץ: ' + err.message);
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'העלה והתחל ניתוח';
            }
        } finally {
            this.isSubmitting = false;
        }
    }

    pollSessionStatus(sessionId) {
        if (this.pollInterval) clearInterval(this.pollInterval);

        const checkStatus = async () => {
            try {
                const session = await API.getSession(sessionId);
                this.currentSession = session;
                this.updateProcessingUI(session);

                if (session.status === 'ready_for_tagging') {
                    clearInterval(this.pollInterval);
                    this.showView('tagging');
                    taggingController.renderTaggingScreen(session);
                } else if (session.status === 'completed') {
                    clearInterval(this.pollInterval);
                    this.showDashboard(session);
                } else if (session.status === 'failed') {
                    clearInterval(this.pollInterval);
                    alert('עיבוד ההקלטה נכשל: ' + (session.error_message || session.status_message));
                    this.showView('welcome');
                }
            } catch (err) {
                console.error('Error polling status:', err);
            }
        };

        checkStatus();
        this.pollInterval = setInterval(checkStatus, 2500);
    }

    updateProcessingUI(session) {
        const progressBar = document.getElementById('processing-progress-bar');
        const progressText = document.getElementById('processing-progress-text');
        const messageEl = document.getElementById('processing-status-message');
        const fileNameEl = document.getElementById('processing-filename');

        if (progressBar) progressBar.style.width = `${session.progress_percent}%`;
        if (progressText) progressText.textContent = `${session.progress_percent}%`;
        if (messageEl) messageEl.textContent = session.status_message;
        if (fileNameEl) fileNameEl.textContent = session.source_filename;
    }

    async openSession(sessionId) {
        try {
            const session = await API.getSession(sessionId);
            this.currentSession = session;
            this.currentSessionId = sessionId;

            if (session.status === 'completed') {
                this.showDashboard(session);
            } else if (session.status === 'ready_for_tagging') {
                this.showView('tagging');
                taggingController.renderTaggingScreen(session);
            } else if (session.status === 'failed') {
                alert('הקלטה זו נכשלה: ' + (session.error_message || 'שגיאה כללית'));
                this.showView('welcome');
            } else {
                this.showView('processing');
                this.pollSessionStatus(sessionId);
            }
        } catch (err) {
            console.error('Error opening session:', err);
            this.showView('welcome');
        }
    }

    async showDashboard(session) {
        this.currentSession = session;
        this.showView('dashboard');

        // Update URL without reload
        const newUrl = new URL(window.location);
        newUrl.searchParams.set('session', session.id);
        window.history.pushState({}, '', newUrl);

        // Header info
        document.getElementById('dash-title').textContent = session.title;
        document.getElementById('dash-filename').textContent = session.source_filename;
        document.getElementById('dash-duration').textContent = audioPlayer.formatTime(session.duration_seconds);
        document.getElementById('dash-child-name').textContent = session.target_child_name || 'לא צוין';

        // Load Audio into global player
        audioPlayer.loadAudio(session.id, session.duration_seconds);

        // Populate speaker filter options
        const filterSelect = document.getElementById('transcript-speaker-filter');
        if (filterSelect) {
            filterSelect.innerHTML = '<option value="">כל הדוברים</option>';
            session.speakers.forEach(spk => {
                const opt = document.createElement('option');
                opt.value = spk.id;
                opt.textContent = `${spk.assigned_name} (${spk.role})`;
                filterSelect.appendChild(opt);
            });
        }

        // Render Report
        if (session.report) {
            this.renderReport(session.report);
        } else {
            try {
                const report = await API.getReport(session.id);
                this.renderReport(report);
            } catch (e) {
                console.log('Report not available:', e);
            }
        }

        // Reset transcript pagination & hour filters
        this.transcriptPage = 1;
        this.selectedHour = null;
        this.renderHourJumpPills();

        // Load Transcript
        await this.reloadTranscript(1, false);

        // Load Acoustics, Coverage & Heatmap
        await this.loadAcousticsAndCoverage(session);

        // Initialize Chat Controller
        if (window.chatController) {
            chatController.setSession(session.id, session);
        }
    }

    async loadAcousticsAndCoverage(session) {
        try {
            const [events, coverage, loudness] = await Promise.all([
                API.getAudioEvents(session.id).catch(() => []),
                API.getCoverage(session.id).catch(() => null),
                API.getLoudnessProfile(session.id).catch(() => ({ points: [] }))
            ]);

            this.currentAudioEvents = events;
            this.firstDistressSeconds = null;

            // Coverage text
            const covTextEl = document.getElementById('dash-coverage-text');
            if (covTextEl && coverage) {
                const transMin = Math.round(coverage.transcribed_seconds / 60);
                const totalMin = Math.round(coverage.total_duration_seconds / 60);
                covTextEl.innerHTML = `תומללו <b>${transMin} דקות</b> (${coverage.coverage_percent}%) מתוך ${totalMin} דקות הקלטה. אותרו <b>${coverage.gaps_count}</b> פערי תמלול ממושכים.`;
            }

            // Find crying events
            const cryingEvents = events.filter(e => e.event_type === 'crying');
            const cryingBadge = document.getElementById('dash-crying-badge');
            const jumpBtn = document.getElementById('dash-jump-distress-btn');

            if (cryingEvents.length > 0) {
                this.firstDistressSeconds = cryingEvents[0].start_time;
                if (cryingBadge) cryingBadge.classList.remove('hidden');
                if (jumpBtn) {
                    jumpBtn.classList.remove('hidden');
                    jumpBtn.innerHTML = `<span>▶ קפוץ לרגע הבכי (${audioPlayer.formatTime(this.firstDistressSeconds)})</span>`;
                }
            } else if (events.length > 0) {
                const firstEvent = events[0];
                this.firstDistressSeconds = firstEvent.start_time;
                if (jumpBtn) {
                    jumpBtn.classList.remove('hidden');
                    jumpBtn.innerHTML = `<span>▶ קפוץ לאירוע קולי (${audioPlayer.formatTime(firstEvent.start_time)})</span>`;
                }
            }

            // Distress Card
            const distressCard = document.getElementById('dash-distress-episodes-card');
            const distressList = document.getElementById('dash-distress-episodes-list');
            const notableEvents = events.filter(e => ['crying', 'screaming', 'loud_span', 'soothing'].includes(e.event_type));

            if (distressCard && distressList) {
                if (notableEvents.length > 0) {
                    distressCard.classList.remove('hidden');
                    distressList.innerHTML = '';
                    notableEvents.forEach(ev => {
                        const row = document.createElement('div');
                        const isCry = ev.event_type === 'crying';
                        row.className = `p-3 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 ${isCry ? 'bg-rose-50/70 border-rose-200' : 'bg-amber-50/60 border-amber-200'}`;
                        const stHms = audioPlayer.formatTime(ev.start_time);
                        const etHms = audioPlayer.formatTime(ev.end_time);

                        row.innerHTML = `
                            <div class="flex items-start gap-2.5">
                                <span class="text-base mt-0.5">${isCry ? '😢' : '⚡'}</span>
                                <div>
                                    <div class="flex items-center gap-2">
                                        <b class="text-xs sm:text-sm text-slate-900">${isCry ? 'אירוע בכי / מצוקה' : 'עלייה חדה בעוצמה / צעקות'}</b>
                                        <span class="text-xs px-2 py-0.5 rounded-full font-mono font-bold bg-white border ${isCry ? 'text-rose-700 border-rose-200' : 'text-amber-700 border-amber-200'}">[${stHms} - ${etHms}]</span>
                                    </div>
                                    <p class="text-xs text-slate-700 mt-0.5">${ev.description || ''}</p>
                                    ${ev.adult_response ? `<p class="text-xs text-indigo-700 font-medium mt-0.5"><b>תגובת צוות:</b> ${ev.adult_response}</p>` : ''}
                                </div>
                            </div>
                            <button type="button" onclick="audioPlayer.seekTo(${ev.start_time})"
                                    class="px-3 py-1.5 rounded-lg text-xs font-bold text-white shadow-sm transition-all flex items-center gap-1 shrink-0 ${isCry ? 'bg-rose-600 hover:bg-rose-700' : 'bg-amber-600 hover:bg-amber-700'}">
                                <span>▶ האזן לאירוע</span>
                            </button>
                        `;
                        distressList.appendChild(row);
                    });
                } else {
                    distressCard.classList.add('hidden');
                }
            }

            // Render Heatmap on Waveform
            if (audioPlayer && audioPlayer.renderHeatmap) {
                audioPlayer.renderHeatmap(loudness.points || [], events, session.duration_seconds);
            }
        } catch (e) {
            console.error('Error loading acoustics:', e);
        }
    }

    jumpToFirstDistress() {
        if (this.firstDistressSeconds !== null && window.audioPlayer) {
            audioPlayer.seekTo(this.firstDistressSeconds);
        }
    }

    renderReport(report) {
        // Executive Summary
        const execEl = document.getElementById('report-exec-summary');
        if (execEl) execEl.textContent = report.executive_summary;

        // Focus Inquiry
        const focusSection = document.getElementById('report-focus-section');
        const focusEl = document.getElementById('report-focus-response');
        if (report.focus_inquiry_response) {
            if (focusSection) focusSection.classList.remove('hidden');
            if (focusEl) focusEl.textContent = report.focus_inquiry_response;
        } else if (focusSection) {
            focusSection.classList.add('hidden');
        }

        // Emotional & Staff Analysis
        const emoEl = document.getElementById('report-emotional-analysis');
        if (emoEl) emoEl.textContent = report.emotional_analysis;

        const staffEl = document.getElementById('report-staff-evaluation');
        if (staffEl) staffEl.textContent = report.staff_evaluation;

        // Recommendations
        const recEl = document.getElementById('report-recommendations');
        if (recEl) recEl.textContent = report.recommendations;

        // Timeline
        const timelineContainer = document.getElementById('report-timeline-container');
        if (timelineContainer && report.timeline_json) {
            timelineContainer.innerHTML = '';
            try {
                const timeline = JSON.parse(report.timeline_json);
                timeline.forEach(item => {
                    const row = document.createElement('div');
                    row.className = 'relative pl-6 pb-6 border-r-2 border-indigo-200 last:border-r-0 mr-4';
                    row.innerHTML = `
                        <div class="absolute -right-2 top-0 w-4 h-4 rounded-full bg-indigo-600 ring-4 ring-indigo-50"></div>
                        <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm hover:border-indigo-300 transition-colors">
                            <div class="flex items-center justify-between mb-2">
                                <h4 class="font-bold text-slate-800 text-sm sm:text-base">${item.phase_name}</h4>
                                <span class="text-xs font-semibold px-2.5 py-1 bg-indigo-50 text-indigo-700 rounded-full">${item.time_range}</span>
                            </div>
                            <p class="text-xs sm:text-sm text-slate-600 leading-relaxed mb-3">${item.summary}</p>
                            <div class="space-y-1">
                                ${(item.key_moments || []).map(km => `
                                    <div class="text-xs text-slate-500 flex items-center gap-1.5">
                                        <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                                        <span>${km}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    `;
                    timelineContainer.appendChild(row);
                });
            } catch (e) {
                console.error('Error parsing timeline JSON:', e);
            }
        }

        // Red flags / Incidents
        const flagsContainer = document.getElementById('report-red-flags-container');
        if (flagsContainer && report.red_flags_json) {
            flagsContainer.innerHTML = '';
            try {
                const flags = JSON.parse(report.red_flags_json);
                if (flags.length === 0) {
                    flagsContainer.innerHTML = `
                        <div class="p-4 bg-emerald-50 text-emerald-800 rounded-xl text-xs sm:text-sm flex items-center gap-2">
                            <svg class="w-5 h-5 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path>
                            </svg>
                            <span>לא זוהו נורות אזהרה או אירועים חריגים במהלך יום זה.</span>
                        </div>
                    `;
                } else {
                    flags.forEach(flag => {
                        const sec = this.parseTimestampToSeconds(flag.timestamp);
                        const card = document.createElement('div');
                        card.className = 'p-4 bg-amber-50/60 border border-amber-200 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3';
                        card.innerHTML = `
                            <div>
                                <div class="flex items-center gap-2 mb-1">
                                    <span class="text-xs font-bold px-2 py-0.5 rounded bg-amber-200 text-amber-900">${flag.severity}</span>
                                    <span class="text-xs font-mono font-semibold text-slate-700">[${flag.timestamp}]</span>
                                </div>
                                <p class="text-xs sm:text-sm font-medium text-slate-800 mb-1">${flag.description}</p>
                                <p class="text-xs text-slate-600 italic font-serif">"${flag.quote}"</p>
                            </div>
                            <button onclick="audioPlayer.seekTo(${sec})" 
                                    class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-medium transition-colors">
                                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"></path>
                                </svg>
                                <span>נגן מרגע זה</span>
                            </button>
                        `;
                        flagsContainer.appendChild(card);
                    });
                }
            } catch (e) {
                console.error('Error parsing red flags JSON:', e);
            }
        }
    }

    renderHourJumpPills() {
        const bar = document.getElementById('transcript-hours-bar');
        if (!bar) return;

        const duration = this.currentSession?.duration_seconds || 0;
        const totalHours = Math.max(1, Math.ceil(duration / 3600));

        bar.innerHTML = '<span class="text-[11px] font-bold text-slate-500 ml-1">דילוג מהיר לשעה:</span>';

        // "All Day" button
        const allBtn = document.createElement('button');
        allBtn.type = 'button';
        allBtn.className = `text-xs px-2.5 py-1 rounded-lg transition-colors font-semibold ${
            this.selectedHour === null
                ? 'bg-indigo-600 text-white shadow-2xs'
                : 'bg-white border border-slate-200 text-slate-700 hover:bg-slate-100'
        }`;
        allBtn.textContent = `כל ההקלטה (~${Math.round(duration / 3600)} שעות)`;
        allBtn.onclick = () => this.selectHour(null);
        bar.appendChild(allBtn);

        // Hour buttons: 1, 2, ..., totalHours
        for (let h = 1; h <= totalHours; h++) {
            const hStart = (h - 1);
            const hEnd = h;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `text-xs px-2.5 py-1 rounded-lg transition-colors font-medium font-mono ${
                this.selectedHour === h
                    ? 'bg-indigo-600 text-white shadow-2xs font-semibold'
                    : 'bg-white border border-slate-200 text-slate-700 hover:bg-slate-100'
            }`;
            btn.textContent = `שעה ${h} (${String(hStart).padStart(2, '0')}:00-${String(hEnd).padStart(2, '0')}:00)`;
            btn.onclick = () => this.selectHour(h);
            bar.appendChild(btn);
        }
    }

    selectHour(hourIndex) {
        this.selectedHour = hourIndex;
        this.transcriptPage = 1;
        this.renderHourJumpPills();
        this.reloadTranscript(1, false);

        if (hourIndex !== null) {
            const seekSec = (hourIndex - 1) * 3600;
            audioPlayer.seekTo(seekSec);
        }
    }

    async reloadTranscript(page = 1, append = false) {
        if (!this.currentSessionId) return;

        this.transcriptPage = page;
        const searchInput = document.getElementById('transcript-search-input');
        const speakerFilter = document.getElementById('transcript-speaker-filter');
        const flaggedFilter = document.getElementById('transcript-flagged-filter');

        const params = {
            search: searchInput ? searchInput.value.trim() : '',
            speaker_id: speakerFilter ? speakerFilter.value : '',
            flagged_only: flaggedFilter ? flaggedFilter.checked : false,
            page: this.transcriptPage,
            page_size: this.transcriptPageSize
        };

        if (this.selectedHour !== null) {
            params.start_time_ge = (this.selectedHour - 1) * 3600;
            params.end_time_le = this.selectedHour * 3600;
        }

        try {
            const data = await API.getTranscriptSegments(this.currentSessionId, params);
            this.transcriptTotalCount = data.total;
            this.transcriptTotalPages = data.total_pages;

            if (append) {
                this.transcriptSegments = this.transcriptSegments.concat(data.items);
            } else {
                this.transcriptSegments = data.items;
            }

            this.renderTranscriptList(data.items, append);
            this.renderPaginationUI();
        } catch (err) {
            console.error('Error reloading transcript:', err);
        }
    }

    renderPaginationUI() {
        const countLabel = document.getElementById('transcript-count-label');
        const rangeBadge = document.getElementById('transcript-time-range-badge');
        const topPagination = document.getElementById('transcript-top-pagination');
        const bottomPagination = document.getElementById('transcript-bottom-pagination');

        const total = this.transcriptTotalCount || 0;
        const page = this.transcriptPage || 1;
        const totalPages = this.transcriptTotalPages || 1;
        const loadedCount = this.transcriptSegments ? this.transcriptSegments.length : 0;

        // 1. Count label
        if (countLabel) {
            if (total === 0) {
                countLabel.textContent = '0 מקטעים נמצאו';
            } else if (loadedCount === total) {
                countLabel.textContent = `מציג את כל ${total} המקטעים בהקלטה`;
            } else {
                const startIdx = (page - 1) * this.transcriptPageSize + 1;
                const endIdx = Math.min(startIdx + this.transcriptSegments.length - 1, total);
                countLabel.textContent = `מציג ${startIdx}–${endIdx} מתוך ${total} מקטעים`;
            }
        }

        // 2. Range badge
        if (rangeBadge && this.transcriptSegments && this.transcriptSegments.length > 0) {
            const first = this.transcriptSegments[0];
            const last = this.transcriptSegments[this.transcriptSegments.length - 1];
            rangeBadge.textContent = `${audioPlayer.formatTime(first.start_time)} - ${audioPlayer.formatTime(last.end_time)}`;
        } else if (rangeBadge) {
            rangeBadge.textContent = '00:00:00 - 00:00:00';
        }

        // 3. Top mini pagination
        if (topPagination) {
            topPagination.innerHTML = `
                <button type="button" 
                        onclick="app.changeTranscriptPage(${page - 1})"
                        ${page <= 1 ? 'disabled class="px-1.5 py-0.5 text-slate-300 cursor-not-allowed"' : 'class="px-1.5 py-0.5 text-slate-600 hover:text-indigo-600 hover:bg-slate-200 rounded transition-colors font-bold"'}
                        title="עמוד קודם">
                    ‹
                </button>
                <span class="font-medium text-slate-700 px-1 text-[11px]">
                    עמוד ${page} מתוך ${totalPages}
                </span>
                <button type="button" 
                        onclick="app.changeTranscriptPage(${page + 1})"
                        ${page >= totalPages ? 'disabled class="px-1.5 py-0.5 text-slate-300 cursor-not-allowed"' : 'class="px-1.5 py-0.5 text-slate-600 hover:text-indigo-600 hover:bg-slate-200 rounded transition-colors font-bold"'}
                        title="עמוד הבא">
                    ›
                </button>
            `;
        }

        // 4. Bottom full pagination & Load More
        if (bottomPagination) {
            bottomPagination.innerHTML = '';

            // Left side: Load More button
            const leftCol = document.createElement('div');
            leftCol.className = 'flex items-center gap-2';

            if (page < totalPages && loadedCount < total) {
                const loadMoreBtn = document.createElement('button');
                loadMoreBtn.type = 'button';
                loadMoreBtn.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 rounded-xl text-xs font-semibold transition-colors shadow-2xs';
                loadMoreBtn.innerHTML = `
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 13l-7 7-7-7m14-8l-7 7-7-7"></path>
                    </svg>
                    <span>טען עוד ${Math.min(this.transcriptPageSize, total - loadedCount)} מקטעים (המשך גלילה)</span>
                `;
                loadMoreBtn.onclick = () => this.loadMoreTranscript();
                leftCol.appendChild(loadMoreBtn);
            }
            bottomPagination.appendChild(leftCol);

            // Right side: Pagination buttons
            const rightCol = document.createElement('div');
            rightCol.className = 'flex items-center gap-1 flex-wrap';

            // First page button
            const firstBtn = document.createElement('button');
            firstBtn.type = 'button';
            firstBtn.disabled = page <= 1;
            firstBtn.className = `px-2 py-1 text-xs rounded-lg font-medium transition-colors ${page <= 1 ? 'text-slate-300 cursor-not-allowed' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'}`;
            firstBtn.textContent = '« ראשון';
            firstBtn.onclick = () => this.changeTranscriptPage(1);
            rightCol.appendChild(firstBtn);

            // Prev button
            const prevBtn = document.createElement('button');
            prevBtn.type = 'button';
            prevBtn.disabled = page <= 1;
            prevBtn.className = `px-2 py-1 text-xs rounded-lg font-medium transition-colors ${page <= 1 ? 'text-slate-300 cursor-not-allowed' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'}`;
            prevBtn.textContent = '‹ קודם';
            prevBtn.onclick = () => this.changeTranscriptPage(page - 1);
            rightCol.appendChild(prevBtn);

            // Numeric page buttons
            const startP = Math.max(1, page - 2);
            const endP = Math.min(totalPages, page + 2);
            for (let p = startP; p <= endP; p++) {
                const pBtn = document.createElement('button');
                pBtn.type = 'button';
                pBtn.className = `w-7 h-7 text-xs rounded-lg font-bold transition-all ${
                    p === page
                        ? 'bg-indigo-600 text-white shadow-2xs'
                        : 'bg-white border border-slate-200 hover:bg-slate-100 text-slate-700'
                }`;
                pBtn.textContent = p;
                pBtn.onclick = () => this.changeTranscriptPage(p);
                rightCol.appendChild(pBtn);
            }

            // Next button
            const nextBtn = document.createElement('button');
            nextBtn.type = 'button';
            nextBtn.disabled = page >= totalPages;
            nextBtn.className = `px-2 py-1 text-xs rounded-lg font-medium transition-colors ${page >= totalPages ? 'text-slate-300 cursor-not-allowed' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'}`;
            nextBtn.textContent = 'הבא ›';
            nextBtn.onclick = () => this.changeTranscriptPage(page + 1);
            rightCol.appendChild(nextBtn);

            // Last page button
            const lastBtn = document.createElement('button');
            lastBtn.type = 'button';
            lastBtn.disabled = page >= totalPages;
            lastBtn.className = `px-2 py-1 text-xs rounded-lg font-medium transition-colors ${page >= totalPages ? 'text-slate-300 cursor-not-allowed' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'}`;
            lastBtn.textContent = 'אחרון »';
            lastBtn.onclick = () => this.changeTranscriptPage(totalPages);
            rightCol.appendChild(lastBtn);

            bottomPagination.appendChild(rightCol);
        }
    }

    changeTranscriptPage(page) {
        if (page < 1 || page > this.transcriptTotalPages) return;
        this.reloadTranscript(page, false);
        const container = document.getElementById('transcript-container');
        if (container) container.scrollTo({ top: 0, behavior: 'smooth' });
    }

    changeTranscriptPageSize(newSize) {
        this.transcriptPageSize = parseInt(newSize, 10);
        this.transcriptPage = 1;
        this.reloadTranscript(1, false);
    }

    loadMoreTranscript() {
        if (this.transcriptPage < this.transcriptTotalPages) {
            this.reloadTranscript(this.transcriptPage + 1, true);
        }
    }

    renderTranscriptList(segments, append = false) {
        const container = document.getElementById('transcript-container');
        if (!container) return;

        if (!append) {
            container.innerHTML = '';
        }

        if (segments.length === 0 && !append) {
            container.innerHTML = `
                <div class="p-8 text-center text-slate-400 text-sm">
                    לא נמצאו מקטעי תמלול התואמים את החיפוש או שעה זו.
                </div>
            `;
            return;
        }

        const fragment = document.createDocumentFragment();

        segments.forEach(seg => {
            const hms = audioPlayer.formatTime(seg.start_time);
            const isChild = this.currentSession && this.currentSession.target_child_name && 
                            seg.speaker_name.includes(this.currentSession.target_child_name);
            const isTeacher = seg.speaker_name.includes('גננת');

            const item = document.createElement('div');
            item.id = `transcript-seg-${seg.id}`;
            item.className = `p-3 rounded-xl border border-transparent hover:border-slate-200 hover:bg-slate-50/70 transition-all cursor-pointer select-none ${
                seg.is_flagged ? 'bg-amber-50/40 border-amber-200' : ''
            }`;
            item.dataset.startTime = seg.start_time;
            item.dataset.endTime = seg.end_time;

            // Click on transcript row immediately seeks audio!
            item.onclick = () => {
                audioPlayer.seekTo(seg.start_time);
            };

            item.innerHTML = `
                <div class="flex items-center justify-between gap-2 mb-1">
                    <div class="flex items-center gap-2">
                        <span class="text-xs font-bold px-2 py-0.5 rounded-full ${
                            isChild ? 'badge-focus-child' : (isTeacher ? 'badge-teacher' : 'badge-peer')
                        }">
                            ${seg.speaker_name}
                        </span>
                        ${seg.is_flagged ? '<span class="text-xs bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-medium">אירוע חריג</span>' : ''}
                    </div>
                    <span class="text-xs font-mono text-slate-400 hover:text-indigo-600 transition-colors">
                        ${hms}
                    </span>
                </div>
                <p class="text-sm text-slate-700 leading-relaxed pr-1">
                    ${seg.text}
                </p>
            `;

            fragment.appendChild(item);
        });

        container.appendChild(fragment);
    }

    setupAudioSync() {
        let lastAutoPageTime = 0;

        audioPlayer.onTimeUpdate((currTime) => {
            if (!this.transcriptSegments || this.transcriptSegments.length === 0) return;

            // Find current active segment
            const activeSeg = this.transcriptSegments.find(
                s => currTime >= s.start_time && currTime <= s.end_time
            );

            if (activeSeg && activeSeg.id !== this.activeSegmentId) {
                // Remove highlight from previous
                if (this.activeSegmentId) {
                    const prevEl = document.getElementById(`transcript-seg-${this.activeSegmentId}`);
                    if (prevEl) prevEl.classList.remove('active-segment');
                }

                // Add highlight to new
                this.activeSegmentId = activeSeg.id;
                const newEl = document.getElementById(`transcript-seg-${activeSeg.id}`);
                if (newEl) {
                    newEl.classList.add('active-segment');
                    newEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            } else if (!activeSeg && audioPlayer.isPlaying) {
                // If audio is playing and we crossed past the loaded page boundary
                // (throttle check to once every 4 seconds)
                const now = Date.now();
                if (now - lastAutoPageTime > 4000) {
                    const lastLoadedSeg = this.transcriptSegments[this.transcriptSegments.length - 1];
                    if (lastLoadedSeg && currTime > lastLoadedSeg.end_time && this.transcriptPage < this.transcriptTotalPages) {
                        lastAutoPageTime = now;
                        this.changeTranscriptPage(this.transcriptPage + 1);
                    }
                }
            }
        });
    }

    async loadRecentSessions() {
        try {
            const sessions = await API.getSessions();
            const listContainer = document.getElementById('recent-sessions-list');
            if (!listContainer) return;

            if (sessions.length === 0) {
                listContainer.innerHTML = '<p class="text-xs text-slate-400">טרם נותחו הקלטות במערכת.</p>';
                return;
            }

            listContainer.innerHTML = '';
            sessions.slice(0, 5).forEach(s => {
                const item = document.createElement('div');
                item.className = 'flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-white hover:border-indigo-400 hover:shadow-sm transition-all cursor-pointer';
                item.onclick = () => this.openSession(s.id);

                const dur = audioPlayer.formatTime(s.duration_seconds);
                const statusBadge = s.status === 'completed'
                    ? '<span class="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-medium">הושלם</span>'
                    : (s.status === 'ready_for_tagging' 
                        ? '<span class="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800 font-medium">ממתין לתיוג</span>'
                        : '<span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">בעיבוד</span>');

                item.innerHTML = `
                    <div class="flex items-center gap-2">
                        <svg class="w-4 h-4 text-indigo-500" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.707.707L4.586 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.586l3.707-3.707a1 1 0 011.09-.217z" clip-rule="evenodd"></path>
                        </svg>
                        <div>
                            <span class="text-xs sm:text-sm font-semibold text-slate-800 block">${s.title}</span>
                            <span class="text-xs text-slate-400">${dur} • ${s.source_filename}</span>
                        </div>
                    </div>
                    <div>${statusBadge}</div>
                `;
                listContainer.appendChild(item);
            });
        } catch (e) {
            console.log('Error loading recent sessions:', e);
        }
    }

    switchTab(tabName) {
        const tabs = ['report', 'chat', 'transcript', 'timeline'];
        tabs.forEach(t => {
            const btn = document.getElementById(`tab-btn-${t}`);
            const content = document.getElementById(`tab-content-${t}`);
            if (t === tabName) {
                if (btn) btn.className = 'px-4 py-2.5 text-sm font-bold border-b-2 border-indigo-600 text-indigo-600 transition-colors flex items-center gap-1.5';
                if (content) content.classList.remove('hidden');
            } else {
                if (btn) btn.className = 'px-4 py-2.5 text-sm font-medium text-slate-500 hover:text-slate-800 border-b-2 border-transparent transition-colors flex items-center gap-1.5';
                if (content) content.classList.add('hidden');
            }
        });
        if (tabName === 'chat') {
            const input = document.getElementById('chat-input');
            if (input) input.focus();
        }
    }

    async jumpToPlayerTimestamp(seconds) {
        audioPlayer.seekTo(seconds);
        this.switchTab('transcript');
        await this.ensureSegmentVisibleForTime(seconds);
    }

    async ensureSegmentVisibleForTime(seconds) {
        // If hour filter is active and timestamp is outside that hour, reset hour filter
        if (this.selectedHour !== null) {
            const hStart = (this.selectedHour - 1) * 3600;
            const hEnd = this.selectedHour * 3600;
            if (seconds < hStart || seconds > hEnd) {
                this.selectedHour = null;
                this.renderHourJumpPills();
            }
        }

        // Check if segment is already in current loaded container
        const container = document.getElementById('transcript-container');
        if (container) {
            const bubbles = container.querySelectorAll('[data-start-time]');
            let closest = null;
            let minDiff = Infinity;
            bubbles.forEach(b => {
                const t = parseFloat(b.dataset.startTime || '0');
                const diff = Math.abs(t - seconds);
                if (diff < minDiff) {
                    minDiff = diff;
                    closest = b;
                }
            });

            // If we found a segment within 20 seconds on current view, scroll right to it!
            if (closest && minDiff < 20.0) {
                this.highlightAndScrollToElement(closest);
                return;
            }
        }

        // Otherwise, ask backend which page contains this timestamp
        try {
            const pageData = await API.getPageForTime(this.currentSessionId, seconds, this.transcriptPageSize);
            const targetPage = pageData.page || 1;
            await this.reloadTranscript(targetPage, false);

            // Now scroll to segment on newly loaded page
            setTimeout(() => {
                const refreshedContainer = document.getElementById('transcript-container');
                if (!refreshedContainer) return;
                const newBubbles = refreshedContainer.querySelectorAll('[data-start-time]');
                let newClosest = null;
                let newMinDiff = Infinity;
                newBubbles.forEach(b => {
                    const t = parseFloat(b.dataset.startTime || '0');
                    const diff = Math.abs(t - seconds);
                    if (diff < newMinDiff) {
                        newMinDiff = diff;
                        newClosest = b;
                    }
                });
                if (newClosest) {
                    this.highlightAndScrollToElement(newClosest);
                }
            }, 100);
        } catch (e) {
            console.error('Error finding page for time:', e);
        }
    }

    highlightAndScrollToElement(el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('ring-2', 'ring-indigo-500', 'bg-indigo-50/70');
        setTimeout(() => {
            el.classList.remove('ring-2', 'ring-indigo-500', 'bg-indigo-50/70');
        }, 3500);
    }

    parseTimestampToSeconds(ts) {
        if (!ts) return 0;
        const parts = ts.replace('[', '').replace(']', '').split(':').map(Number);
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
        if (parts.length === 2) return parts[0] * 60 + parts[1];
        return 0;
    }

    async promptRegenerateReport() {
        if (!this.currentSessionId) return;
        const currentPrompt = this.currentSession?.focus_prompt || '';
        const newPrompt = prompt('הזן או עדכן את שאלת המיקוד להפקת הדוח מחדש (התמלול והדוברים כבר שמורים):', currentPrompt);
        if (newPrompt === null) return; // user cancelled

        try {
            const orKey = document.getElementById('cfg-openrouter-key')?.value.trim();
            const orModel = document.getElementById('cfg-openrouter-model')?.value.trim();

            await API.regenerateReport(this.currentSessionId, {
                focus_prompt: newPrompt,
                openrouter_api_key: orKey || undefined,
                openrouter_model: orModel || undefined
            });

            this.showView('processing');
            this.pollSessionStatus(this.currentSessionId);
        } catch (err) {
            alert('שגיאה בהפעלת הפקת הדוח מחדש: ' + err.message);
        }
    }

    openTaggingForCurrentSession() {
        if (!this.currentSession) return;
        this.showView('tagging');
        taggingController.renderTaggingScreen(this.currentSession);
    }

    downloadMarkdown() {
        if (!this.currentSessionId) return;
        window.open(API.getReportMarkdownUrl(this.currentSessionId), '_blank');
    }

    printReport() {
        window.print();
    }
}

window.app = new KindergartenMonitorApp();
