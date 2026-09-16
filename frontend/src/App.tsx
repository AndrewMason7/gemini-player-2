import { Gamepad2, Headphones } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AudioPlayer } from "./audio/audio_player";
import { AudioRecorder } from "./audio/audio_recorder";
import { ControlBar } from "./components/ControlBar";
import { EditorCanvas } from "./components/EditorCanvas";
import { GamePreview } from "./components/GamePreview";
import { ThoughtAura } from "./components/ThoughtAura";

interface DiffChunk {
	start_line: number;
	start_col: number;
	end_line: number;
	end_col: number;
	new_text: string;
	description?: string;
}

interface CursorData {
	line: number;
	ch: number;
	gesture?: string;
	tag?: string;
}

export function App() {
	const [code, setCode] = useState<string>("// Loading starter game...");
	const [geminiCursor, setGeminiCursor] = useState<CursorData | null>(null);
	const [pendingEdits, setPendingEdits] = useState<DiffChunk[] | null>(null);
	const [thoughts, setThoughts] = useState<string[]>([]);
	const [isThinking, setIsThinking] = useState<boolean>(false);
	const [activeReaction, setActiveReaction] = useState<{
		mood: string;
		effect: string;
	} | null>(null);

	const [isConnected, setIsConnected] = useState<boolean>(false);
	const [isMicActive, setIsMicActive] = useState<boolean>(false);
	const [statusState, setStatusState] = useState<
		| "disconnected"
		| "connecting"
		| "reconnecting"
		| "idle"
		| "listening"
		| "speaking"
		| "coding"
	>("disconnected");
	const [statusMessage, setStatusMessage] = useState<string>(
		"Click Connect to start",
	);

	const [transcripts, setTranscripts] = useState<
		Array<{ sender: "user" | "gemini"; text: string }>
	>([]);

	const wsRef = useRef<WebSocket | null>(null);
	const audioRecorderRef = useRef<AudioRecorder | null>(null);
	const audioPlayerRef = useRef<AudioPlayer | null>(null);
	const codeRef = useRef<string>(code);
	const userDisconnectedRef = useRef<boolean>(true);
	const reconnectAttemptRef = useRef<number>(0);
	const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const lastActivityRef = useRef<number>(Date.now());
	const messageQueueRef = useRef<Array<string | ArrayBuffer>>([]);

	// Keep codeRef in sync with code state
	useEffect(() => {
		codeRef.current = code;
	}, [code]);

	// Fetch initial starter code from backend
	useEffect(() => {
		const endpoint =
			window.location.port === "5173"
				? "http://localhost:8000/api/starter-code"
				: "/api/starter-code";
		fetch(endpoint)
			.then((res) => res.json())
			.then((data) => {
				if (data.code) {
					setCode(data.code);
					codeRef.current = data.code;
				}
			})
			.catch((err) => {
				console.warn(
					"Could not fetch starter code from server, using default",
					err,
				);
			});
	}, []);

	// Initialize audio player and cleanup timers on unmount
	useEffect(() => {
		audioPlayerRef.current = new AudioPlayer();
		return () => {
			audioPlayerRef.current?.close();
			userDisconnectedRef.current = true;
			if (reconnectTimeoutRef.current) {
				clearTimeout(reconnectTimeoutRef.current);
			}
			if (heartbeatIntervalRef.current) {
				clearInterval(heartbeatIntervalRef.current);
			}
			wsRef.current?.close();
		};
	}, []);

	// Safe message sending with queueing during reconnection windows
	const sendMessageSafe = useCallback((data: string | ArrayBuffer) => {
		if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
			wsRef.current.send(data);
		} else if (!userDisconnectedRef.current) {
			// Don't queue redundant editor_sync messages since codeRef.current is synced on connect
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
			// Queue message during brief reconnection windows (capped to 50 items)
			if (messageQueueRef.current.length < 50) {
				messageQueueRef.current.push(data);
			}
		}
	}, []);

	// Establish WebSocket connection with auto-reconnect & heartbeat
	const connectWebSocket = useCallback(() => {
		if (
			wsRef.current &&
			(wsRef.current.readyState === WebSocket.OPEN ||
				wsRef.current.readyState === WebSocket.CONNECTING)
		) {
			return;
		}

		userDisconnectedRef.current = false;
		if (reconnectTimeoutRef.current) {
			clearTimeout(reconnectTimeoutRef.current);
			reconnectTimeoutRef.current = null;
		}

		audioPlayerRef.current?.resumeAudio();
		if (reconnectAttemptRef.current === 0) {
			setStatusState("connecting");
			setStatusMessage("Opening real-time channel...");
		}

		const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
		const host =
			window.location.hostname === "localhost"
				? "localhost:8000"
				: window.location.host;
		const wsUrl = `${protocol}//${host}/ws/live`;

		const ws = new WebSocket(wsUrl);
		ws.binaryType = "arraybuffer";

		ws.onopen = () => {
			if (wsRef.current !== ws) return;
			setIsConnected(true);
			reconnectAttemptRef.current = 0;
			lastActivityRef.current = Date.now();
			setStatusState("listening");
			setStatusMessage("Connected to Gemini Live!");

			// Start 20s heartbeat ping
			if (heartbeatIntervalRef.current) {
				clearInterval(heartbeatIntervalRef.current);
			}
			heartbeatIntervalRef.current = setInterval(() => {
				if (ws.readyState === WebSocket.OPEN) {
					// Check for silent connection death (missed pongs / no activity for >45s)
					if (Date.now() - lastActivityRef.current > 45000) {
						console.warn(
							"Heartbeat timeout (missed pongs), closing stale connection",
						);
						ws.close();
						return;
					}
					ws.send(JSON.stringify({ type: "ping", timestamp: Date.now() }));
				}
			}, 20000);

			// Always sync current editor code on connect/reconnect
			ws.send(JSON.stringify({ type: "editor_sync", code: codeRef.current }));

			// Flush any queued user messages
			while (messageQueueRef.current.length > 0) {
				const item = messageQueueRef.current.shift();
				if (item && ws.readyState === WebSocket.OPEN) {
					ws.send(item);
				}
			}
		};

		ws.onmessage = async (event) => {
			if (wsRef.current !== ws) return;
			lastActivityRef.current = Date.now();

			if (event.data instanceof ArrayBuffer) {
				// Binary 24kHz audio from Gemini Live
				setStatusState("speaking");
				await audioPlayerRef.current?.playChunk(event.data);
			} else if (typeof event.data === "string") {
				try {
					const data = JSON.parse(event.data);

					switch (data.type) {
						case "pong":
							// Heartbeat pong received, connection is healthy
							break;

						case "status":
							setStatusState(data.state);
							if (data.message) setStatusMessage(data.message);
							if (data.state === "coding") {
								setIsThinking(true);
								setThoughts([]);
							} else if (data.state === "listening") {
								setIsThinking(false);
							}
							break;

						case "cursor_move":
							setGeminiCursor({
								line: data.line,
								ch: data.ch,
								gesture: data.gesture,
								tag: data.tag,
							});
							break;

						case "thought_stream":
							setIsThinking(true);
							setThoughts((prev) => [...prev, data.text]);
							break;

						case "code_diff":
							setIsThinking(false);
							if (data.edits && data.edits.length > 0) {
								setPendingEdits(data.edits);
							}
							break;

						case "reaction":
							setActiveReaction({
								mood: data.mood || "excited",
								effect: data.effect || "confetti",
							});
							break;

						case "transcript":
							setTranscripts((prev) => {
								const last = prev[prev.length - 1];
								if (
									last &&
									last.sender === data.sender &&
									last.text === data.text
								) {
									return prev;
								}
								return [
									...prev.slice(-15),
									{ sender: data.sender, text: data.text },
								];
							});
							break;

						case "interrupted":
							audioPlayerRef.current?.interrupt();
							setStatusState("listening");
							setStatusMessage("Barged in");
							break;

						default:
							break;
					}
				} catch (e) {
					console.error("Error parsing JSON WebSocket message:", e);
				}
			}
		};

		ws.onerror = (err) => {
			if (wsRef.current !== ws) return;
			console.error("WebSocket error:", err);
		};

		ws.onclose = () => {
			if (wsRef.current !== ws && wsRef.current !== null) return;

			if (heartbeatIntervalRef.current) {
				clearInterval(heartbeatIntervalRef.current);
				heartbeatIntervalRef.current = null;
			}

			setIsConnected(false);
			setIsMicActive(false);
			audioRecorderRef.current?.stop();
			audioPlayerRef.current?.interrupt();
			wsRef.current = null;

			// If user initiated disconnect, do not auto-reconnect
			if (userDisconnectedRef.current) {
				setStatusState("disconnected");
				setStatusMessage("Session ended");
				reconnectAttemptRef.current = 0;
				messageQueueRef.current = [];
				return;
			}

			// Unexpected drop -> schedule auto-reconnect with exponential backoff (1s, 2s, 4s, up to 10s)
			const attempt = reconnectAttemptRef.current;
			const delay = Math.min(1000 * Math.pow(2, attempt), 10000);
			reconnectAttemptRef.current = attempt + 1;

			setStatusState("reconnecting");
			setStatusMessage(
				`Reconnecting in ${(delay / 1000).toFixed(0)}s (attempt ${attempt + 1})...`,
			);

			reconnectTimeoutRef.current = setTimeout(() => {
				if (!userDisconnectedRef.current) {
					connectWebSocket();
				}
			}, delay);
		};

		wsRef.current = ws;
	}, []);

	const disconnectWebSocket = useCallback(() => {
		userDisconnectedRef.current = true;
		if (reconnectTimeoutRef.current) {
			clearTimeout(reconnectTimeoutRef.current);
			reconnectTimeoutRef.current = null;
		}
		if (heartbeatIntervalRef.current) {
			clearInterval(heartbeatIntervalRef.current);
			heartbeatIntervalRef.current = null;
		}
		audioRecorderRef.current?.stop();
		audioPlayerRef.current?.interrupt();
		wsRef.current?.close();
		wsRef.current = null;
		reconnectAttemptRef.current = 0;
		messageQueueRef.current = [];
		lastActivityRef.current = Date.now();
		setIsConnected(false);
		setIsMicActive(false);
		setStatusState("disconnected");
		setStatusMessage("Session disconnected");
	}, []);

	const toggleMic = async () => {
		if (!isConnected || !wsRef.current) return;
		audioPlayerRef.current?.resumeAudio();

		if (isMicActive) {
			audioRecorderRef.current?.stop();
			setIsMicActive(false);
			sendMessageSafe(JSON.stringify({ type: "audio_stream_end" }));
		} else {
			try {
				// Stream 16kHz Linear PCM directly to Gemini Live API
				const recorder = new AudioRecorder((pcmBytes) => {
					if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
						wsRef.current.send(pcmBytes.buffer as ArrayBuffer);
					}
				});
				await recorder.start();
				audioRecorderRef.current = recorder;
				setIsMicActive(true);
			} catch (err) {
				console.error("Failed to access microphone:", err);
				alert("Microphone permission denied or device error.");
			}
		}
	};

	const handleInterrupt = () => {
		audioPlayerRef.current?.interrupt();
		sendMessageSafe(JSON.stringify({ type: "user_interrupt" }));
	};

	const handleSendText = (text: string) => {
		sendMessageSafe(JSON.stringify({ type: "text_input", text }));
		setTranscripts((prev) => [...prev, { sender: "user", text }]);
	};

	const handleCodeChange = (newCode: string) => {
		setCode(newCode);
		codeRef.current = newCode;
		sendMessageSafe(
			JSON.stringify({ type: "editor_sync", code: newCode }),
		);
	};

	const handleEditsApplied = () => {
		setPendingEdits(null);
	};

	return (
		<div className="flex flex-col w-screen h-screen bg-[#030712] text-slate-100 overflow-hidden font-sans">
			{/* Navigation / Header */}
			<header className="flex items-center justify-between px-6 py-2.5 bg-slate-900/80 backdrop-blur-md border-b border-slate-800 z-10">
				<div className="flex items-center gap-3">
					<div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-cyan-500 via-indigo-500 to-purple-500 flex items-center justify-center shadow-lg shadow-cyan-500/20">
						<Gamepad2 className="w-5 h-5 text-slate-950" />
					</div>
					<div>
						<div className="flex items-center gap-2">
							<h1 className="text-sm font-bold tracking-tight text-white">
								Gemini: Player 2
							</h1>
							<span className="text-[10px] font-semibold tracking-wide px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/80">
								Google Labs Concept
							</span>
						</div>
						<p className="text-[11px] text-slate-400">
							Real-Time Co-Presence Pair Programming • Gemini Live API +
							Antigravity Engine
						</p>
					</div>
				</div>

				{/* Live speech transcription ticker */}
				<div className="hidden lg:flex items-center gap-2 max-w-lg px-3 py-1 rounded-full bg-slate-950/70 border border-slate-800 text-xs text-slate-300 overflow-hidden">
					<span className="w-2 h-2 rounded-full bg-cyan-400 shrink-0"></span>
					<span className="truncate">
						{transcripts.length > 0 ? (
							<>
								<strong className="text-cyan-300 capitalize">
									{transcripts[transcripts.length - 1].sender}:
								</strong>{" "}
								{transcripts[transcripts.length - 1].text}
							</>
						) : (
							<span className="text-slate-500 italic">
								"Say: 'Gemini, let's make the ball bouncy and paddle purple!'"
							</span>
						)}
					</span>
				</div>

				<div className="flex items-center gap-2 text-xs text-slate-400">
					<span className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800/60 border border-slate-700/60 font-mono text-[11px]">
						<Headphones className="w-3 h-3 text-cyan-400" />
						Headphones Recommended
					</span>
				</div>
			</header>

			{/* Main Split-Screen Workspace */}
			<main className="relative flex-1 flex flex-col md:flex-row gap-3 p-3 min-h-0 bg-[#060a14]">
				{/* Left: Code Editor with Player 2 Cursor */}
				<div className="relative flex-1 h-full min-w-0">
					<EditorCanvas
						code={code}
						onChange={handleCodeChange}
						geminiCursor={geminiCursor}
						pendingEdits={pendingEdits}
						onEditsApplied={handleEditsApplied}
					/>
					{/* Floating Antigravity Thought Aura (Anchored to Editor, never overlaying Game) */}
					<ThoughtAura
						thoughts={thoughts}
						isThinking={isThinking}
						onDismiss={() => setThoughts([])}
					/>
				</div>

				{/* Right: Live Arcade Sandbox Canvas */}
				<div className="w-full md:w-[480px] lg:w-[540px] h-full shrink-0 min-w-0">
					<GamePreview code={code} reaction={activeReaction} />
				</div>
			</main>

			{/* Control Bar */}
			<ControlBar
				isConnected={isConnected}
				isMicActive={isMicActive}
				statusState={statusState}
				statusMessage={statusMessage}
				onToggleConnect={
					isConnected ||
					statusState === "connecting" ||
					statusState === "reconnecting"
						? disconnectWebSocket
						: connectWebSocket
				}
				onToggleMic={toggleMic}
				onInterrupt={handleInterrupt}
				onSendText={handleSendText}
			/>
		</div>
	);
}

export default App;
