import { Brain, Check, ChevronDown, ChevronUp, Sparkles, X } from "lucide-react";
import type React from "react";
import { useEffect, useRef, useState } from "react";

interface ThoughtAuraProps {
	thoughts: string[];
	isThinking: boolean;
	onDismiss?: () => void;
}

export const ThoughtAura: React.FC<ThoughtAuraProps> = ({
	thoughts,
	isThinking,
	onDismiss,
}) => {
	const [isOpen, setIsOpen] = useState<boolean>(true);
	const [isDismissed, setIsDismissed] = useState<boolean>(false);
	const scrollRef = useRef<HTMLDivElement | null>(null);

	// Reset dismissed state and expand whenever active thinking begins
	useEffect(() => {
		if (isThinking) {
			setIsDismissed(false);
			setIsOpen(true);
		} else if (thoughts.length > 0) {
			// Auto-dismiss 4 seconds after reasoning finishes so it never stays stuck
			const timer = setTimeout(() => {
				setIsDismissed(true);
			}, 4000);
			return () => clearTimeout(timer);
		}
	}, [isThinking, thoughts.length]);

	// Auto-scroll as new reasoning tokens stream in
	useEffect(() => {
		if (scrollRef.current) {
			scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
		}
	}, [thoughts]);

	if (isDismissed || (thoughts.length === 0 && !isThinking)) {
		return null;
	}

	return (
		<div className="absolute bottom-4 right-4 z-20 w-80 max-w-[calc(100%-2rem)] rounded-xl border border-cyan-500/30 bg-slate-900/95 backdrop-blur-md shadow-2xl overflow-hidden transition-all duration-300 pointer-events-auto">
			{/* Header bar with glowing aura pulse */}
			<div className="w-full flex items-center justify-between px-3.5 py-2.5 bg-gradient-to-r from-cyan-950/70 via-slate-900 to-purple-950/70 border-b border-cyan-500/20 select-none">
				<button
					type="button"
					onClick={() => setIsOpen(!isOpen)}
					className="flex items-center gap-2 flex-1 text-left cursor-pointer"
				>
					<div className="relative flex items-center justify-center">
						{isThinking ? (
							<>
								<Brain className="w-4 h-4 text-cyan-400 animate-pulse" />
								<span className="absolute -inset-1 rounded-full bg-cyan-400/40 animate-ping"></span>
							</>
						) : (
							<Check className="w-4 h-4 text-emerald-400" />
						)}
					</div>
					<span className="text-xs font-semibold text-cyan-200">
						{isThinking ? "Gemini Live Thoughts..." : "Reasoning Complete"}
					</span>
				</button>

				<div className="flex items-center gap-1.5 text-cyan-400">
					<button
						type="button"
						onClick={() => setIsOpen(!isOpen)}
						className="p-1 rounded hover:bg-slate-800/80 transition-colors"
						title={isOpen ? "Collapse" : "Expand"}
					>
						{isOpen ? (
							<ChevronUp className="w-3.5 h-3.5" />
						) : (
							<ChevronDown className="w-3.5 h-3.5" />
						)}
					</button>
					<button
						type="button"
						onClick={() => {
							setIsDismissed(true);
							onDismiss?.();
						}}
						className="p-1 rounded hover:bg-red-500/20 text-slate-400 hover:text-red-300 transition-colors"
						title="Close"
					>
						<X className="w-3.5 h-3.5" />
					</button>
				</div>
			</div>

			{/* Streamed thought content */}
			{isOpen && (
				<div
					ref={scrollRef}
					className="p-3 max-h-48 overflow-y-auto text-[11px] font-mono text-cyan-100/90 leading-relaxed bg-slate-950/80 space-y-1.5 scrollbar-thin"
				>
					{thoughts.map((t, idx) => (
						<p
							key={`thought-${idx}-${t.slice(0, 15)}`}
							className="whitespace-pre-wrap animate-fadeIn"
						>
							{t}
						</p>
					))}
					{isThinking ? (
						<div className="flex items-center gap-1 text-cyan-400 text-[10px] animate-pulse">
							<span>●</span>
							<span>●</span>
							<span>●</span>
							<span className="ml-1 italic font-sans">
								Antigravity worker formulating edits
							</span>
						</div>
					) : (
						<div className="flex items-center gap-1 text-emerald-400/80 text-[10px] italic font-sans pt-1">
							<Sparkles className="w-3 h-3 text-emerald-400" />
							<span>Surgical edits applied to Monaco</span>
						</div>
					)}
				</div>
			)}
		</div>
	);
};
