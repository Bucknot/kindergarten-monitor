// Frontend API client
const API = {
    async getSessions() {
        const res = await fetch('/api/sessions');
        if (!res.ok) throw new Error('Failed to fetch sessions');
        return await res.json();
    },

    async getSession(id) {
        const res = await fetch(`/api/sessions/${id}`);
        if (!res.ok) throw new Error('Failed to fetch session');
        return await res.json();
    },

    async createSessionFromPath(data) {
        const res = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to create session');
        }
        return await res.json();
    },

    async uploadSession(formData) {
        const res = await fetch('/api/sessions/upload', {
            method: 'POST',
            body: formData
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to upload session');
        }
        return await res.json();
    },

    async deleteSession(id) {
        const res = await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to delete session');
        return await res.json();
    },

    async configureSpeakers(sessionId, data) {
        const res = await fetch(`/api/speakers/${sessionId}/configure`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to configure speakers');
        }
        return await res.json();
    },

    async getSpeakerSamples(sessionId, speakerId) {
        const res = await fetch(`/api/speakers/${sessionId}/${speakerId}/samples`);
        if (!res.ok) throw new Error('Failed to fetch speaker samples');
        return await res.json();
    },

    async getAllSpeakerSamples(sessionId) {
        const res = await fetch(`/api/speakers/${sessionId}/samples`);
        if (!res.ok) throw new Error('Failed to fetch all speaker samples');
        return await res.json();
    },

    async getTranscriptSegments(sessionId, params = {}) {
        const url = new URL(`/api/transcripts/${sessionId}`, window.location.origin);
        Object.entries(params).forEach(([key, val]) => {
            if (val !== undefined && val !== null && val !== '') {
                url.searchParams.append(key, val);
            }
        });
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch transcript');
        return await res.json();
    },

    async getPageForTime(sessionId, timeSeconds, pageSize = 250, params = {}) {
        try {
            const url = new URL(`/api/transcripts/${sessionId}/page-for-time`, window.location.origin);
            url.searchParams.append('time_seconds', timeSeconds);
            url.searchParams.append('page_size', pageSize);
            if (params.speaker_id) url.searchParams.append('speaker_id', params.speaker_id);
            if (params.flagged_only) url.searchParams.append('flagged_only', 'true');
            const res = await fetch(url);
            if (!res.ok) return { page: 1 };
            return await res.json();
        } catch (e) {
            return { page: 1 };
        }
    },

    async getReport(sessionId) {
        const res = await fetch(`/api/reports/${sessionId}`);
        if (!res.ok) throw new Error('Failed to fetch report');
        return await res.json();
    },

    async regenerateReport(sessionId, data = {}) {
        const res = await fetch(`/api/sessions/${sessionId}/regenerate-report`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to regenerate report');
        }
        return await res.json();
    },

    getAudioStreamUrl(sessionId) {
        return `/api/audio/stream/${sessionId}`;
    },

    getReportMarkdownUrl(sessionId) {
        return `/api/reports/${sessionId}/markdown`;
    },

    async sendChatMessage(sessionId, data) {
        const res = await fetch(`/api/chat/${sessionId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to send chat message');
        }
        return await res.json();
    },

    async getAudioEvents(sessionId, eventType = null) {
        let url = `/api/audio-events/${sessionId}`;
        if (eventType) url += `?event_type=${encodeURIComponent(eventType)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch audio events');
        return await res.json();
    },

    async getCoverage(sessionId) {
        const res = await fetch(`/api/audio-events/${sessionId}/coverage`);
        if (!res.ok) throw new Error('Failed to fetch coverage stats');
        return await res.json();
    },

    async getLoudnessProfile(sessionId) {
        const res = await fetch(`/api/audio-events/${sessionId}/loudness`);
        if (!res.ok) throw new Error('Failed to fetch loudness profile');
        return await res.json();
    }
};
