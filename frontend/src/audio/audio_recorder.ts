/**
 * AudioRecorder captures microphone input, downsamples to 16,000 Hz,
 * and encodes to 16-bit Linear PCM for the Gemini Live API.
 */
export class AudioRecorder {
	private audioContext: AudioContext | null = null;
	private mediaStream: MediaStream | null = null;
	private processor: ScriptProcessorNode | null = null;
	private input: MediaStreamAudioSourceNode | null = null;
	private muteNode: GainNode | null = null;
	private onAudioData: (pcmBytes: Uint8Array) => void;
	public isRecording: boolean = false;

	constructor(onAudioData: (pcmBytes: Uint8Array) => void) {
		this.onAudioData = onAudioData;
	}

	async start(): Promise<void> {
		if (this.isRecording) return;

		this.mediaStream = await navigator.mediaDevices.getUserMedia({
			audio: {
				channelCount: 1,
				sampleRate: 16000,
				echoCancellation: true,
				noiseSuppression: true,
				autoGainControl: true,
			},
		});

		this.audioContext = new (
			window.AudioContext ||
			(window as unknown as { webkitAudioContext: typeof AudioContext })
				.webkitAudioContext
		)({
			sampleRate: 16000,
		});

		this.input = this.audioContext.createMediaStreamSource(this.mediaStream);
		// 2048 buffer size gives ~128ms chunks at 16kHz
		this.processor = this.audioContext.createScriptProcessor(2048, 1, 1);

		this.processor.onaudioprocess = (e) => {
			if (!this.isRecording) return;
			const inputData = e.inputBuffer.getChannelData(0);
			const pcm16 = this.floatTo16BitPCM(inputData);
			this.onAudioData(pcm16);
		};

		// Route through a muted gain node to prevent mic audio looping back to speakers
		// while keeping the ScriptProcessorNode processing pipeline active in Web Audio
		this.muteNode = this.audioContext.createGain();
		this.muteNode.gain.value = 0;

		this.input.connect(this.processor);
		this.processor.connect(this.muteNode);
		this.muteNode.connect(this.audioContext.destination);
		this.isRecording = true;
	}

	stop(): void {
		this.isRecording = false;

		if (this.muteNode) {
			this.muteNode.disconnect();
			this.muteNode = null;
		}
		if (this.processor) {
			this.processor.onaudioprocess = null;
			this.processor.disconnect();
			this.processor = null;
		}
		if (this.input) {
			this.input.disconnect();
			this.input = null;
		}
		if (this.mediaStream) {
			this.mediaStream.getTracks().forEach((t) => {
				t.stop();
			});
			this.mediaStream = null;
		}
		if (this.audioContext) {
			this.audioContext.close();
			this.audioContext = null;
		}
	}

	private floatTo16BitPCM(float32Array: Float32Array): Uint8Array {
		const buffer = new ArrayBuffer(float32Array.length * 2);
		const view = new DataView(buffer);
		let offset = 0;

		for (let i = 0; i < float32Array.length; i++, offset += 2) {
			const s = Math.max(-1, Math.min(1, float32Array[i]));
			// Convert Float (-1.0 to 1.0) to 16-bit signed integer (-32768 to 32767)
			view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true); // Little-endian
		}

		return new Uint8Array(buffer);
	}
}
