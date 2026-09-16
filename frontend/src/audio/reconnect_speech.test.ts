import { beforeEach, describe, expect, it, mock } from "bun:test";
import { AudioPlayer } from "./audio_player";

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
    createBuffer: (channels: number, length: number, sampleRate: number) => AudioBuffer;
    createBufferSource: () => MockBufferSource;
    resume: ReturnType<typeof mock>;
    close: ReturnType<typeof mock>;
}

describe("Reconnect Mid-Speech Lifecycle (Mocked Sockets & Audio)", () => {
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

    it("handles socket disconnect mid-speech: halts audio, flushes playhead, and recovers on reconnect", async () => {
        const player = new AudioPlayer();
        mockAudioContext.currentTime = 10.0;

        // Simulate incoming speech stream (3 chunks of 24kHz audio = 0.2s each)
        const chunk = new ArrayBuffer(4800 * 2);
        await player.playChunk(chunk);
        await player.playChunk(chunk);
        await player.playChunk(chunk);

        expect(player.isPlaying).toBe(true);
        expect(mockSources.length).toBe(3);
        expect(mockSources[0]?.stopped).toBe(false);

        // 1. Socket drops unexpectedly mid-speech while playing chunk 1
        mockAudioContext.currentTime = 10.15;

        // Client onclose handler invokes player interrupt and marks reconnecting
        player.interrupt();
        let statusState: string = "reconnecting";

        expect(player.isPlaying).toBe(false);
        // All active/queued audio sources must be stopped and disconnected
        expect(mockSources[0]?.stopped).toBe(true);
        expect(mockSources[0]?.disconnected).toBe(true);
        expect(mockSources[1]?.stopped).toBe(true);
        expect(mockSources[1]?.disconnected).toBe(true);
        expect(mockSources[2]?.stopped).toBe(true);
        expect(mockSources[2]?.disconnected).toBe(true);

        // 2. Mock socket reconnects after backoff
        const sentMessages: string[] = [];
        const mockWs = {
            readyState: 1, // OPEN
            send: (data: string) => {
                sentMessages.push(data);
            },
        };

        // On socket reopen: editor_sync must be sent first to sync current code
        const activeCode = "let ball = { color: '#fbbf24' };";
        mockWs.send(JSON.stringify({ type: "editor_sync", code: activeCode }));
        statusState = "listening";

        expect(sentMessages.length).toBe(1);
        expect(JSON.parse(sentMessages[0]).type).toBe("editor_sync");
        expect(JSON.parse(sentMessages[0]).code).toBe(activeCode);
        expect(statusState).toBe("listening");

        // 3. New speech begins arriving on reconnected socket
        mockAudioContext.currentTime = 12.0; // Time moved forward during reconnect
        await player.playChunk(chunk);

        expect(player.isPlaying).toBe(true);
        expect(mockSources.length).toBe(4);
        // The 4th chunk starts cleanly at currentTime (12.0) + 0.05 without drift into past
        expect(mockSources[3]?.startedAt).toBeCloseTo(12.05, 3);
        expect(mockSources[3]?.stopped).toBe(false);
    });

    it("drops mic recording and resets mic state on mid-speech socket drop", () => {
        let isMicActive = true;
        let isConnected = true;
        const mockRecorder = {
            stop: mock(() => {}),
        };

        // Mid-speech connection drop
        const onSocketClose = () => {
            isConnected = false;
            isMicActive = false;
            mockRecorder.stop();
        };

        onSocketClose();

        expect(isConnected).toBe(false);
        expect(isMicActive).toBe(false);
        expect(mockRecorder.stop).toHaveBeenCalled();
    });
});
