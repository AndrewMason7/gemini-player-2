import {
	Mic,
	MicOff,
	Radio,
	Send,
	Sparkles,
	Square,
	Volume2,
} from "lucide-react";
import type React from "react";
import { useState } from "react";

interface ControlBarProps {
	isConnected: boolean;
	isMicActive: boolean;
	statusState:
		| "disconnected"
		| "connecting"
		| "reconnecting"
		| "idle"
		| "listening"
		| "speaking"
		| "coding";
	statusMessage?: string;
	onToggleConnect: () => void;
	onToggleMic: () => void;
	onInterrupt: () => void;
	onSendText: (text: string) => void;
}

export const ControlBar: React.FC<ControlBarProps> = ({
	isConnected,
	isMicActive,
	statusState,
	statusMessage,
	onToggleConnect,
	onToggleMic,
	onInterrupt,
	onSendText,
}) => {
	const [inputText, setInputText] = useState("");

	const isConnectingOrReconnecting =
		statusState === "connecting" || statusState === "reconnecting";
	const canDisconnect = isConnected || isConnectingOrReconnecting;

	const handleSend = (e: React.FormEvent) => {
		e.preventDefault();
		if (inputText.trim()) {
			onSendText(inputText.trim());
			setInputText("");
		}
	};

	const getStatusBadge = () => {
		switch (statusState) {
			case "speaking":
				return (
					<span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
						<Volume2 className="w-3.5 h-3.5 animate-bounce text-cyan-400" />
						Speaking
					</span>
				);
			case "coding":
				return (
					<span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/40 animate-pulse">
						<Sparkles className="w-3.5 h-3.5 text-purple-400" />
						Worker Coding...
					</span>
				);
			case "listening":
				return (
					<span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
						<span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
						Listening
					</span>
				);
			case "connecting":
				return (
					<span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40">
						Connecting...
					</span>
				);
			case "reconnecting":
				return (
					<span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40">
						<span className="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span>
						Reconnecting...
					</span>
				);
			default:
				return (
					<span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
						Offline
					</span>
				);
		}
	};

	return (
		<footer className="w-full bg-slate-900/95 border-t border-slate-800 px-6 py-3 flex flex-wrap items-center justify-between gap-4 select-none z-10">
			{/* Left side: Status & Connection */}
			<div className="flex items-center gap-3">
				<button
					type="button"
					onClick={onToggleConnect}
					className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg font-medium text-xs transition cursor-pointer ${
						canDisconnect
							? "bg-red-500/20 text-red-300 border border-red-500/30 hover:bg-red-500/30"
							: "bg-cyan-500 text-slate-950 font-semibold hover:bg-cyan-400 shadow-lg shadow-cyan-500/20"
					}`}
				>
					<Radio
						className={`w-3.5 h-3.5 ${isConnected ? "animate-pulse" : ""}`}
					/>
					{canDisconnect ? "Disconnect" : "Connect Player 2"}
				</button>

				{getStatusBadge()}

				{statusMessage && (
					<span className="text-xs text-slate-400 font-mono hidden md:inline truncate max-w-xs">
						{statusMessage}
					</span>
				)}
			</div>

			{/* Center: Live Text Prompt Input */}
			<form
				onSubmit={handleSend}
				className="flex-1 max-w-md flex items-center gap-2"
			>
				<input
					type="text"
					value={inputText}
					onChange={(e) => setInputText(e.target.value)}
					placeholder={
						canDisconnect
							? "Talk or type: 'Make paddle neon pink'..."
							: "Connect to talk with Player 2"
					}
					disabled={!canDisconnect}
					className="flex-1 px-3.5 py-1.5 text-xs rounded-lg bg-slate-950/80 border border-slate-800 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition"
				/>
				<button
					type="submit"
					disabled={!canDisconnect || !inputText.trim()}
					className="p-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:hover:bg-cyan-600 text-slate-950 transition cursor-pointer"
					title="Send text prompt"
				>
					<Send className="w-3.5 h-3.5" />
				</button>
			</form>

			{/* Right side: Audio controls & reactions */}
			<div className="flex items-center gap-2">
				{isConnected && (
					<button
						type="button"
						onClick={onInterrupt}
						className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/30 text-amber-300 text-xs transition cursor-pointer"
						title="Interrupt Gemini speaking (Barge-in)"
					>
						<Square className="w-3 h-3 fill-amber-300" />
						<span>Barge In</span>
					</button>
				)}

				<button
					type="button"
					onClick={onToggleMic}
					disabled={!isConnected}
					className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer ${
						!isConnected
							? "opacity-40 bg-slate-800 text-slate-500"
							: isMicActive
								? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/30 shadow-lg shadow-emerald-500/10"
								: "bg-red-500/20 text-red-300 border border-red-500/40 hover:bg-red-500/30"
					}`}
					title={isMicActive ? "Mute Microphone" : "Unmute Microphone"}
				>
					{isMicActive ? (
						<>
							<Mic className="w-3.5 h-3.5 animate-pulse text-emerald-400" />
							<span>Mic On (16kHz)</span>
						</>
					) : (
						<>
							<MicOff className="w-3.5 h-3.5 text-red-400" />
							<span>Mic Muted</span>
						</>
					)}
				</button>
			</div>
		</footer>
	);
};
