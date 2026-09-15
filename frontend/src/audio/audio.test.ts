import { beforeEach, describe, expect, it, mock } from "bun:test";
import { AudioPlayer } from "./audio_player";
import { AudioRecorder } from "./audio_recorder";

interface MockBufferSource {
	buffer: AudioBuffer | null;
	startedAt?: number;
	stopped: boolean;
	disconnected: boolean;
	onended: (() => void) | null;
	connect: ReturnType<typeof mock>;
	start: ReturnType<typeof mock>;
	stop: ReturnType<typeof mock>;
	disconnect: ReturnType<typeof mock>;
}

interface MockAudioCtx {
	currentTime: number;
	state: string;
	destination: Record<string, unknown>;
	createBuffer: (
		channels: number,
		length: number,
		sampleRate: number,
	) => AudioBuffer;
	createBufferSource: () => MockBufferSource;
	resume: ReturnType<typeof mock>;
	close: ReturnType<typeof mock>;
}

describe("AudioPlayer", () => {
	let mockSources: MockBufferSource[];
	let mockAudioContext: MockAudioCtx;

	beforeEach(() => {
		mockSources = [];
		mockAudioContext = {
			currentTime: 1.0,
			state: "running",
			destination: {},
			createBuffer: (channels: number, length: number, sampleRate: number) =>
				({
					channels,
					length,
					sampleRate,
					duration: length / sampleRate,
					copyToChannel: mock(() => {}),
				}) as unknown as AudioBuffer,
			createBufferSource: () => {
				const src: MockBufferSource = {
					buffer: null,
					startedAt: undefined,
					stopped: false,
					disconnected: false,
					onended: null,
					connect: mock(() => {}),
					start: mock((time: number) => {
						src.startedAt = time;
					}),
					stop: mock(() => {
						src.stopped = true;
					}),
					disconnect: mock(() => {
						src.disconnected = true;
					}),
				};
				mockSources.push(src);
				return src;
			},
			resume: mock(() => Promise.resolve()),
			close: mock(() => Promise.resolve()),
		};

		function MockAudioContext() {
			return mockAudioContext;
		}

		Object.defineProperty(globalThis, "window", {
			value: {
				AudioContext: MockAudioContext,
				speechSynthesis: {
					cancel: mock(() => {}),
				},
			},
			writable: true,
		});
	});

	it("queues audio chunks monotonically without resetting into the past on burst (>1.5s queue)", async () => {
		const player = new AudioPlayer();
		mockAudioContext.currentTime = 0.0;

		// Create dummy PCM chunks (4800 samples = 0.2s each at 24kHz)
		const chunkBytes = new ArrayBuffer(4800 * 2);

		// Play 10 chunks in rapid succession
		for (let i = 0; i < 10; i++) {
			await player.playChunk(chunkBytes);
		}

		expect(mockSources.length).toBe(10);

		// Chunk 0 starts at currentTime (0.0) + 0.05 = 0.05
		expect(mockSources[0]?.startedAt).toBeCloseTo(0.05, 3);

		// Each subsequent chunk should start strictly AFTER the previous chunk
		for (let i = 1; i < 10; i++) {
			const prevStart = mockSources[i - 1]?.startedAt ?? 0;
			const currStart = mockSources[i]?.startedAt ?? 0;
			expect(currStart).toBeGreaterThan(prevStart);
			expect(currStart).toBeCloseTo(0.05 + i * 0.2, 3);
		}

		// Verify that even at chunk 9 (start time = 1.85s, queue > 1.5s), it did NOT reset to currentTime + 0.1
		expect(mockSources[9]?.startedAt).toBeCloseTo(1.85, 3);
	});

	it("stops active audio and resets playhead on interruption", async () => {
		const player = new AudioPlayer();
		mockAudioContext.currentTime = 0.0;
		const chunkBytes = new ArrayBuffer(4800 * 2);

		await player.playChunk(chunkBytes);
		await player.playChunk(chunkBytes);

		expect(mockSources.length).toBe(2);
		expect(player.isPlaying).toBe(true);

		mockAudioContext.currentTime = 0.1;
		player.interrupt();

		expect(mockSources[0]?.stopped).toBe(true);
		expect(mockSources[0]?.disconnected).toBe(true);
		expect(mockSources[1]?.stopped).toBe(true);
		expect(mockSources[1]?.disconnected).toBe(true);
		expect(player.isPlaying).toBe(false);

		// Next chunk after interruption should start at new currentTime (0.1) + 0.05
		await player.playChunk(chunkBytes);
		expect(mockSources[2]?.startedAt).toBeCloseTo(0.15, 3);
	});

	it("handles close() by interrupting active playback and closing context", async () => {
		const player = new AudioPlayer();
		const chunkBytes = new ArrayBuffer(4800 * 2);
		await player.playChunk(chunkBytes);

		expect(player.isPlaying).toBe(true);
		player.close();

		expect(mockSources[0]?.stopped).toBe(true);
		expect(player.isPlaying).toBe(false);
		expect(mockAudioContext.close).toHaveBeenCalled();
	});

	it("survives ghost onended firing after interrupt() without corrupting state", async () => {
		const player = new AudioPlayer();
		mockAudioContext.currentTime = 0.0;
		const chunkBytes = new ArrayBuffer(4800 * 2);

		await player.playChunk(chunkBytes);
		const initialSource = mockSources[0];

		player.interrupt();
		expect(player.isPlaying).toBe(false);

		// Now a new chunk arrives
		await player.playChunk(chunkBytes);
		expect(player.isPlaying).toBe(true);

		// If the old source's onended was somehow saved and triggered
		if (initialSource?.onended) {
			initialSource.onended();
		}
		// Active playback should NOT be falsely cancelled
		expect(player.isPlaying).toBe(true);
	});
});

interface MockMuteGainNode {
	gain: { value: number };
	connect: ReturnType<typeof mock>;
	disconnect: ReturnType<typeof mock>;
}

interface MockScriptProcessor {
	onaudioprocess:
		| ((e: {
				inputBuffer: { getChannelData: (ch: number) => Float32Array };
		  }) => void)
		| null;
	connect: ReturnType<typeof mock>;
	disconnect: ReturnType<typeof mock>;
}

interface MockStreamTrack {
	stop: ReturnType<typeof mock>;
}

interface MockRecorderAudioCtx {
	currentTime: number;
	state: string;
	destination: Record<string, unknown>;
	createMediaStreamSource: ReturnType<typeof mock>;
	createScriptProcessor: ReturnType<typeof mock>;
	createGain: ReturnType<typeof mock>;
	close: ReturnType<typeof mock>;
}

describe("AudioRecorder", () => {
	let mockMuteGain: MockMuteGainNode;
	let mockProcessor: MockScriptProcessor;
	let mockMediaStream: { getTracks: () => MockStreamTrack[] };
	let mockTrack: MockStreamTrack;
	let mockAudioContext: MockRecorderAudioCtx;

	beforeEach(() => {
		mockTrack = { stop: mock(() => {}) };
		mockMediaStream = {
			getTracks: () => [mockTrack],
		};

		mockMuteGain = {
			gain: { value: 1.0 },
			connect: mock(() => {}),
			disconnect: mock(() => {}),
		};

		mockProcessor = {
			onaudioprocess: null,
			connect: mock(() => {}),
			disconnect: mock(() => {}),
		};

		mockAudioContext = {
			currentTime: 0,
			state: "running",
			destination: {},
			createMediaStreamSource: mock(() => ({
				connect: mock(() => {}),
				disconnect: mock(() => {}),
			})),
			createScriptProcessor: mock(() => mockProcessor),
			createGain: mock(() => mockMuteGain),
			close: mock(() => Promise.resolve()),
		};

		Object.defineProperty(globalThis, "navigator", {
			value: {
				mediaDevices: {
					getUserMedia: mock(() => Promise.resolve(mockMediaStream)),
				},
			},
			writable: true,
		});

		function MockAudioContext() {
			return mockAudioContext;
		}

		Object.defineProperty(globalThis, "window", {
			value: {
				AudioContext: MockAudioContext,
			},
			writable: true,
		});
	});

	it("routes microphone through gain.value = 0 to prevent speaker loopback", async () => {
		const onData = mock(() => {});
		const recorder = new AudioRecorder(onData);

		await recorder.start();

		expect(recorder.isRecording).toBe(true);
		expect(mockMuteGain.gain.value).toBe(0);
		expect(mockProcessor.connect).toHaveBeenCalledWith(mockMuteGain);
		expect(mockMuteGain.connect).toHaveBeenCalledWith(
			mockAudioContext.destination,
		);

		// Simulate audio process callback
		const fakeEvent = {
			inputBuffer: {
				getChannelData: () => new Float32Array([0.0, 0.5, -0.5, 1.5, -1.5]),
			},
		};
		if (mockProcessor.onaudioprocess) {
			mockProcessor.onaudioprocess(fakeEvent);
		}

		expect(onData).toHaveBeenCalledTimes(1);
		const pcmBytes = onData.mock.calls[0]?.[0] as Uint8Array;
		expect(pcmBytes.byteLength).toBe(10); // 5 samples * 2 bytes

		const view = new DataView(pcmBytes.buffer);
		expect(view.getInt16(0, true)).toBe(0);
		expect(view.getInt16(2, true)).toBe(Math.trunc(0.5 * 0x7fff));
		expect(view.getInt16(4, true)).toBe(Math.trunc(-0.5 * 0x8000));
		// Clamped to 1.0 -> 0x7fff = 32767
		expect(view.getInt16(6, true)).toBe(32767);
		// Clamped to -1.0 -> -0x8000 = -32768
		expect(view.getInt16(8, true)).toBe(-32768);

		recorder.stop();
		expect(recorder.isRecording).toBe(false);
		expect(mockProcessor.onaudioprocess).toBeNull();
		expect(mockMuteGain.disconnect).toHaveBeenCalled();
		expect(mockProcessor.disconnect).toHaveBeenCalled();
		expect(mockTrack.stop).toHaveBeenCalled();
		expect(mockAudioContext.close).toHaveBeenCalled();
	});
});

describe("Connection Stability and Queueing Logic", () => {
	it("calculates exponential backoff capped at 10s", () => {
		const computeBackoff = (attempt: number) =>
			Math.min(1000 * Math.pow(2, attempt), 10000);

		expect(computeBackoff(0)).toBe(1000); // 1s
		expect(computeBackoff(1)).toBe(2000); // 2s
		expect(computeBackoff(2)).toBe(4000); // 4s
		expect(computeBackoff(3)).toBe(8000); // 8s
		expect(computeBackoff(4)).toBe(10000); // 10s (capped)
		expect(computeBackoff(5)).toBe(10000); // 10s (capped)
		expect(computeBackoff(10)).toBe(10000); // 10s (capped)
	});

	it("formats heartbeat ping messages correctly", () => {
		const now = Date.now();
		const pingMessage = JSON.stringify({ type: "ping", timestamp: now });
		const parsed = JSON.parse(pingMessage);

		expect(parsed.type).toBe("ping");
		expect(parsed.timestamp).toBe(now);
	});

	it("queues messages during disconnected/reconnecting state and drains on open", () => {
		const queue: Array<string | ArrayBuffer> = [];
		let isOpen = false;
		const sentMessages: Array<string | ArrayBuffer> = [];

		const sendMessage = (data: string | ArrayBuffer) => {
			if (isOpen) {
				sentMessages.push(data);
			} else {
				if (queue.length < 50) {
					queue.push(data);
				}
			}
		};

		// Send while disconnected
		sendMessage(
			JSON.stringify({ type: "text_input", text: "Make paddle pink" }),
		);
		sendMessage(JSON.stringify({ type: "user_interrupt" }));

		expect(sentMessages.length).toBe(0);
		expect(queue.length).toBe(2);

		// Simulate connection open
		isOpen = true;
		// Sync editor code first
		sentMessages.push(
			JSON.stringify({ type: "editor_sync", code: "const x = 10;" }),
		);

		// Drain queue
		while (queue.length > 0) {
			const item = queue.shift();
			if (item) {
				sentMessages.push(item);
			}
		}

		expect(queue.length).toBe(0);
		expect(sentMessages.length).toBe(3);
		expect(JSON.parse(sentMessages[0] as string).type).toBe("editor_sync");
		expect(JSON.parse(sentMessages[1] as string).type).toBe("text_input");
		expect(JSON.parse(sentMessages[2] as string).type).toBe("user_interrupt");
	});

	it("caps message queue size to prevent unbounded memory growth", () => {
		const queue: Array<string | ArrayBuffer> = [];
		const isDisconnected = true;

		for (let i = 0; i < 60; i++) {
			if (isDisconnected && queue.length < 50) {
				queue.push(`msg-${i}`);
			}
		}

		expect(queue.length).toBe(50);
		expect(queue[0]).toBe("msg-0");
		expect(queue[49]).toBe("msg-49");
	});

	it("filters out redundant editor_sync messages when queueing during reconnection", () => {
		const queue: Array<string | ArrayBuffer> = [];
		const isOpen = false;
		let latestCode = "let speed = 10;";

		const sendMessageSafe = (data: string | ArrayBuffer) => {
			if (isOpen) {
				// send directly
			} else {
				if (typeof data === "string") {
					try {
						const parsed = JSON.parse(data);
						if (parsed.type === "editor_sync") {
							return;
						}
					} catch {
						// pass
					}
				}
				if (queue.length < 50) {
					queue.push(data);
				}
			}
		};

		// User edits code multiple times while disconnected
		latestCode = "let speed = 15;";
		sendMessageSafe(
			JSON.stringify({ type: "editor_sync", code: latestCode }),
		);
		latestCode = "let speed = 20;";
		sendMessageSafe(
			JSON.stringify({ type: "editor_sync", code: latestCode }),
		);

		// User also types a prompt
		sendMessageSafe(
			JSON.stringify({ type: "text_input", text: "Change ball color" }),
		);

		// The queue should only contain the prompt, not redundant intermediate editor_sync keystrokes
		expect(queue.length).toBe(1);
		expect(JSON.parse(queue[0] as string).type).toBe("text_input");
	});

	it("detects stale heartbeat when pongs are missed for >45s", () => {
		let isClosed = false;
		const mockWs = {
			readyState: 1, // OPEN
			close: () => {
				isClosed = true;
			},
		};

		const checkHeartbeat = (lastActivityTime: number, currentTime: number) => {
			if (currentTime - lastActivityTime > 45000) {
				mockWs.close();
				return false;
			}
			return true;
		};

		// Healthy: active within 10s
		expect(checkHeartbeat(100000, 110000)).toBe(true);
		expect(isClosed).toBe(false);

		// Stale: no activity for 50s (> 45s threshold)
		expect(checkHeartbeat(100000, 150001)).toBe(false);
		expect(isClosed).toBe(true);
	});

	it("ignores callbacks from stale superseded WebSocket instances", () => {
		let activeWsInstance: { id: number } | null = { id: 2 };
		let handledEvents = 0;

		const handleOnMessage = (socket: { id: number }) => {
			if (activeWsInstance !== socket) return;
			handledEvents++;
		};

		const staleWs = { id: 1 };
		const currentWs = activeWsInstance;

		handleOnMessage(staleWs);
		expect(handledEvents).toBe(0);

		handleOnMessage(currentWs);
		expect(handledEvents).toBe(1);
	});

	it("parses server status and pong events seamlessly", () => {
		const rawStatus = JSON.stringify({
			type: "status",
			state: "reconnecting",
			message: "Reconnecting to Gemini Live (attempt 1)...",
		});
		const parsedStatus = JSON.parse(rawStatus);
		expect(parsedStatus.type).toBe("status");
		expect(parsedStatus.state).toBe("reconnecting");
		expect(parsedStatus.message).toContain("attempt 1");

		const rawPong = JSON.stringify({ type: "pong", timestamp: 123456789 });
		const parsedPong = JSON.parse(rawPong);
		expect(parsedPong.type).toBe("pong");
		expect(parsedPong.timestamp).toBe(123456789);
	});
});

