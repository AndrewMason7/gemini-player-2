/**
 * AudioPlayer plays 24,000 Hz Linear PCM audio chunks received from Gemini Live API,
 * with jitter queuing and instant cancellation on barge-in interruption.
 */
export class AudioPlayer {
	private audioContext: AudioContext | null = null;
	private nextPlayTime: number = 0;
	private activeSources: AudioBufferSourceNode[] = [];
	public isPlaying: boolean = false;

	private initContext(): AudioContext {
		if (!this.audioContext || this.audioContext.state === "closed") {
			this.audioContext = new (
				window.AudioContext ||
				(window as unknown as { webkitAudioContext: typeof AudioContext })
					.webkitAudioContext
			)({
				sampleRate: 24000,
			});
		}
		if (this.audioContext.state === "suspended") {
			this.audioContext.resume();
		}
		return this.audioContext;
	}

	/**
	 * Enqueues and plays a chunk of 24kHz 16-bit PCM bytes.
	 */
	async playChunk(pcmBytes: ArrayBuffer): Promise<void> {
		const ctx = this.initContext();
		const dataView = new DataView(pcmBytes);
		const numSamples = Math.floor(pcmBytes.byteLength / 2);
		const float32Data = new Float32Array(numSamples);

		for (let i = 0; i < numSamples; i++) {
			const int16 = dataView.getInt16(i * 2, true); // Little-endian
			float32Data[i] = int16 < 0 ? int16 / 0x8000 : int16 / 0x7fff;
		}

		const audioBuffer = ctx.createBuffer(1, numSamples, 24000);
		audioBuffer.copyToChannel(float32Data, 0);

		const source = ctx.createBufferSource();
		source.buffer = audioBuffer;
		source.connect(ctx.destination);

		const currentTime = ctx.currentTime;
		if (this.nextPlayTime <= currentTime) {
			this.nextPlayTime = currentTime + 0.05; // 50ms initial jitter buffer
		}

		source.start(this.nextPlayTime);
		this.activeSources.push(source);
		this.isPlaying = true;

		source.onended = () => {
			const idx = this.activeSources.indexOf(source);
			if (idx !== -1) {
				this.activeSources.splice(idx, 1);
			}
			if (this.activeSources.length === 0) {
				this.isPlaying = false;
			}
		};

		this.nextPlayTime += audioBuffer.duration;
	}

	/**
	 * Ensures the AudioContext is resumed upon user interaction.
	 */
	public resumeAudio(): void {
		this.initContext();
		if (this.audioContext && this.audioContext.state === "suspended") {
			this.audioContext.resume();
		}
	}

	/**
	 * Instantly stops all queued playback on barge-in / interruption.
	 */
	interrupt(): void {
		if (typeof window !== "undefined" && "speechSynthesis" in window) {
			window.speechSynthesis.cancel();
		}
		for (const src of this.activeSources) {
			try {
				src.onended = null;
				src.stop();
				src.disconnect();
			} catch {
				// Source might already have ended
			}
		}
		this.activeSources = [];
		this.nextPlayTime = 0;
		this.isPlaying = false;
	}

	close(): void {
		this.interrupt();
		if (this.audioContext) {
			this.audioContext.close();
			this.audioContext = null;
		}
	}
}
