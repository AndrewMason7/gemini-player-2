import { Play, RotateCcw, Terminal } from "lucide-react";
import type React from "react";
import { useEffect, useRef, useState } from "react";

interface GamePreviewProps {
	code: string;
}

export const GamePreview: React.FC<GamePreviewProps> = ({ code }) => {
	const iframeRef = useRef<HTMLIFrameElement | null>(null);
	const [key, setKey] = useState<number>(0);
	const [error, setError] = useState<string | null>(null);

	const restartGame = () => {
		setKey((prev) => prev + 1);
		setError(null);
	};

	useEffect(() => {
		const iframe = iframeRef.current;
		if (!iframe) return;
		setError(null);
		void key; // Explicit trigger for game restart

		const sanitizedCode = code.replace(/<\/script/gi, "<\\/script");

		const htmlContent = `
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8">
          <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
              background: #090d16;
              display: flex;
              align-items: center;
              justify-content: center;
              height: 100vh;
              overflow: hidden;
              font-family: system-ui, sans-serif;
            }
            canvas {
              background: radial-gradient(circle at center, #111827 0%, #030712 100%);
              border: 1px solid #1f2937;
              border-radius: 8px;
              box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
              cursor: pointer;
              max-width: 100%;
              max-height: 100%;
              user-select: none;
              touch-action: none;
            }
          </style>
        </head>
        <body>
          <canvas id="gameCanvas" width="480" height="320"></canvas>
          <script>
            window.onerror = function(msg, url, line) {
              window.parent.postMessage({ type: "GAME_ERROR", message: msg + " (line " + line + ")" }, "*");
            };
            try {
              ${sanitizedCode}
            } catch (err) {
              window.parent.postMessage({ type: "GAME_ERROR", message: err.message }, "*");
            }
          </script>
        </body>
      </html>
    `;

		iframe.srcdoc = htmlContent;
	}, [code, key]);

	useEffect(() => {
		const handleMessage = (e: MessageEvent) => {
			if (e.source !== iframeRef.current?.contentWindow) return;
			if (e.data?.type === "GAME_ERROR") {
				setError(String(e.data.message));
			}
		};
		window.addEventListener("message", handleMessage);
		return () => window.removeEventListener("message", handleMessage);
	}, []);

	return (
		<div className="relative flex flex-col w-full h-full rounded-xl overflow-hidden border border-slate-800 bg-[#090d16] shadow-2xl">
			{/* Header bar */}
			<div className="flex items-center justify-between px-4 py-2 bg-slate-900/90 border-b border-slate-800 text-xs text-slate-400 select-none">
				<div className="flex items-center gap-2">
					<Play className="w-3.5 h-3.5 text-emerald-400 fill-emerald-400" />
					<span className="font-semibold text-slate-200">
						Interactive Canvas Sandbox
					</span>
					<span className="text-[10px] bg-emerald-950/80 border border-emerald-800/60 text-emerald-400 px-1.5 py-0.5 rounded font-mono">
						HMR 12ms
					</span>
				</div>
				<div className="flex items-center gap-2">
					<button
						type="button"
						onClick={restartGame}
						className="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs transition cursor-pointer"
						title="Restart Canvas Game"
					>
						<RotateCcw className="w-3 h-3" />
						<span>Restart</span>
					</button>
				</div>
			</div>

			{/* Main Canvas Iframe */}
			<div className="relative flex-1 w-full h-full bg-[#090d16] flex items-center justify-center p-2">
				<iframe
					ref={iframeRef}
					title="Game Runner"
					sandbox="allow-scripts allow-same-origin"
					className="w-full h-full border-none rounded-lg"
				/>

				{error && (
					<div className="absolute bottom-4 left-4 right-4 bg-red-950/90 border border-red-800/80 text-red-200 text-xs p-3 rounded-lg backdrop-blur-md flex items-center gap-2">
						<Terminal className="w-4 h-4 text-red-400 shrink-0" />
						<span className="font-mono">{error}</span>
					</div>
				)}
			</div>

			{/* Footer / Instructions */}
			<div className="px-4 py-1.5 bg-slate-950/80 border-t border-slate-800/80 text-[11px] text-slate-400 flex items-center justify-between">
				<div className="flex items-center gap-2">
					<div className="flex items-center gap-1">
						<kbd className="px-1 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-300">
							←
						</kbd>
						<kbd className="px-1 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-300">
							→
						</kbd>
						<span className="text-slate-500">/</span>
						<kbd className="px-1 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-300">
							A
						</kbd>
						<kbd className="px-1 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-300">
							D
						</kbd>
						<span className="text-slate-500">/</span>
						<span className="text-slate-300 font-medium">Mouse</span>
					</div>
					<span className="text-slate-500">•</span>
					<div className="flex items-center gap-1">
						<kbd className="px-1 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-300">
							Space
						</kbd>
						<span className="text-slate-400">Launch</span>
					</div>
				</div>
				<span className="text-slate-400 italic">
					Try: "Gemini, increase ball speed and make bricks glow"
				</span>
			</div>
		</div>
	);
};
