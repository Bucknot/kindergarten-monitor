// Audio Player Controller with Range-Streaming & Transcript Sync
class AudioPlayerController {
    constructor() {
        this.audio = new Audio();
        this.isPlaying = false;
        this.currentTime = 0;
        this.duration = 0;
        this.playbackRate = 1.0;
        this.timeUpdateListeners = [];
        this.isUserScrubbing = false;

        this.initDOMElements();
        this.attachEventListeners();
    }

    initDOMElements() {
        this.barElement = document.getElementById('audio-player-bar');
        this.playPauseBtn = document.getElementById('player-play-btn');
        this.playIcon = document.getElementById('player-play-icon');
        this.pauseIcon = document.getElementById('player-pause-icon');
        this.timeCurrentEl = document.getElementById('player-time-current');
        this.timeTotalEl = document.getElementById('player-time-total');
        this.scrubSlider = document.getElementById('player-scrub-slider');
        this.speedBtn = document.getElementById('player-speed-btn');
        this.speedLabel = document.getElementById('player-speed-label');
        this.skipBackBtn = document.getElementById('player-skip-back');
        this.skipForwardBtn = document.getElementById('player-skip-forward');
    }

    attachEventListeners() {
        if (!this.playPauseBtn) return;

        this.playPauseBtn.addEventListener('click', () => this.togglePlay());

        this.audio.addEventListener('play', () => {
            this.isPlaying = true;
            this.updatePlayPauseUI();
        });

        this.audio.addEventListener('pause', () => {
            this.isPlaying = false;
            this.updatePlayPauseUI();
        });

        this.audio.addEventListener('timeupdate', () => {
            this.currentTime = this.audio.currentTime;
            if (!this.isUserScrubbing && this.scrubSlider) {
                this.scrubSlider.value = this.currentTime;
            }
            if (this.timeCurrentEl) {
                this.timeCurrentEl.textContent = this.formatTime(this.currentTime);
            }
            // Trigger listeners (e.g. transcript sync)
            this.timeUpdateListeners.forEach(fn => fn(this.currentTime));
        });

        this.audio.addEventListener('loadedmetadata', () => {
            this.duration = this.audio.duration || 0;
            if (this.scrubSlider) {
                this.scrubSlider.max = this.duration;
            }
            if (this.timeTotalEl) {
                this.timeTotalEl.textContent = this.formatTime(this.duration);
            }
        });

        if (this.scrubSlider) {
            this.scrubSlider.addEventListener('mousedown', () => { this.isUserScrubbing = true; });
            this.scrubSlider.addEventListener('touchstart', () => { this.isUserScrubbing = true; });
            this.scrubSlider.addEventListener('input', (e) => {
                if (this.timeCurrentEl) {
                    this.timeCurrentEl.textContent = this.formatTime(parseFloat(e.target.value));
                }
            });
            this.scrubSlider.addEventListener('change', (e) => {
                this.seekTo(parseFloat(e.target.value));
                this.isUserScrubbing = false;
            });
        }

        if (this.skipBackBtn) {
            this.skipBackBtn.addEventListener('click', () => {
                this.seekTo(Math.max(0, this.audio.currentTime - 15));
            });
        }

        if (this.skipForwardBtn) {
            this.skipForwardBtn.addEventListener('click', () => {
                this.seekTo(Math.min(this.duration, this.audio.currentTime + 15));
            });
        }

        if (this.speedBtn) {
            this.speedBtn.addEventListener('click', () => {
                const speeds = [1.0, 1.25, 1.5, 2.0];
                const nextIdx = (speeds.indexOf(this.playbackRate) + 1) % speeds.length;
                this.playbackRate = speeds[nextIdx];
                this.audio.playbackRate = this.playbackRate;
                if (this.speedLabel) {
                    this.speedLabel.textContent = `${this.playbackRate}x`;
                }
            });
        }
    }

    loadAudio(sessionId, initialDuration = 0) {
        const streamUrl = API.getAudioStreamUrl(sessionId);
        this.audio.src = streamUrl;
        this.audio.playbackRate = this.playbackRate;
        if (initialDuration > 0) {
            this.duration = initialDuration;
            if (this.scrubSlider) this.scrubSlider.max = initialDuration;
            if (this.timeTotalEl) this.timeTotalEl.textContent = this.formatTime(initialDuration);
        }
        if (this.barElement) {
            this.barElement.classList.remove('hidden');
        }
    }

    togglePlay() {
        if (this.audio.paused) {
            this.audio.play().catch(err => console.log('Audio playback prevented:', err));
        } else {
            this.audio.pause();
        }
    }

    play() {
        this.audio.play().catch(err => console.log('Audio playback prevented:', err));
    }

    pause() {
        this.audio.pause();
    }

    seekTo(seconds) {
        this.audio.currentTime = seconds;
        if (this.timeCurrentEl) {
            this.timeCurrentEl.textContent = this.formatTime(seconds);
        }
        if (!this.isPlaying) {
            this.play();
        }
    }

    onTimeUpdate(callback) {
        this.timeUpdateListeners.push(callback);
    }

    updatePlayPauseUI() {
        if (this.playIcon && this.pauseIcon) {
            if (this.isPlaying) {
                this.playIcon.classList.add('hidden');
                this.pauseIcon.classList.remove('hidden');
            } else {
                this.playIcon.classList.remove('hidden');
                this.pauseIcon.classList.add('hidden');
            }
        }
    }

    formatTime(seconds) {
        if (isNaN(seconds) || seconds < 0) return '00:00:00';
        const hrs = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }

    renderHeatmap(loudnessPoints = [], events = [], duration = 0) {
        const heatmapContainer = document.getElementById('player-heatmap-container');
        const canvas = document.getElementById('player-waveform-canvas');
        const markersContainer = document.getElementById('player-heatmap-markers');
        if (!heatmapContainer || !canvas) return;

        const dur = duration || this.duration || 1;

        // Click to seek handler on heatmap container
        if (!this.heatmapClickBound) {
            heatmapContainer.addEventListener('click', (e) => {
                const rect = heatmapContainer.getBoundingClientRect();
                const clickX = e.clientX - rect.left;
                const ratio = Math.max(0, Math.min(1, clickX / rect.width));
                const seekTarget = ratio * (this.duration || dur);
                this.seekTo(seekTarget);
            });
            this.heatmapClickBound = true;
        }

        // Draw waveform on canvas
        const ctx = canvas.getContext('2d');
        const width = canvas.width = heatmapContainer.clientWidth || 600;
        const height = canvas.height = heatmapContainer.clientHeight || 14;

        ctx.clearRect(0, 0, width, height);

        if (loudnessPoints && loudnessPoints.length > 0) {
            ctx.fillStyle = '#cbd5e1';
            const numBars = Math.min(width, loudnessPoints.length);
            const step = loudnessPoints.length / numBars;

            for (let i = 0; i < numBars; i++) {
                const pt = loudnessPoints[Math.floor(i * step)];
                if (!pt) continue;
                // Normalize dB from -45dB (0 height) to 0dB (full height)
                const db = pt.full_db || -40;
                const norm = Math.max(0.1, Math.min(1.0, (db + 45) / 40));
                const barHeight = norm * height;
                ctx.fillRect(i * (width / numBars), height - barHeight, (width / numBars) - 0.5, barHeight);
            }
        }

        // Render colored event markers
        if (markersContainer) {
            markersContainer.innerHTML = '';
            events.forEach(ev => {
                const stRatio = Math.max(0, Math.min(1, ev.start_time / dur));
                const etRatio = Math.max(0, Math.min(1, ev.end_time / dur));
                const leftPct = (stRatio * 100).toFixed(2);
                const widthPct = Math.max(0.5, (etRatio - stRatio) * 100).toFixed(2);

                const marker = document.createElement('div');
                marker.className = 'absolute top-0 bottom-0 pointer-events-auto cursor-pointer transition-opacity hover:opacity-100 opacity-80';
                marker.style.left = `${leftPct}%`;
                marker.style.width = `${widthPct}%`;

                if (ev.event_type === 'crying') {
                    marker.className += ' bg-rose-500/80 hover:bg-rose-600 shadow-sm z-10';
                    marker.title = `🚨 בכי: ${this.formatTime(ev.start_time)} - ${ev.description || ''}`;
                } else if (ev.event_type === 'screaming' || ev.event_type === 'loud_span') {
                    marker.className += ' bg-amber-500/70 hover:bg-amber-600 z-10';
                    marker.title = `⚡ רעש/צעקה: ${this.formatTime(ev.start_time)} - ${ev.description || ''}`;
                } else if (ev.event_type === 'speech_gap') {
                    marker.className += ' bg-slate-400/40';
                    marker.title = `⚠ פער תמלול: ${this.formatTime(ev.start_time)}`;
                }

                marker.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.seekTo(ev.start_time);
                });

                markersContainer.appendChild(marker);
            });
        }
    }
}

window.audioPlayer = new AudioPlayerController();
