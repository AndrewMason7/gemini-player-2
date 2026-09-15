import Editor, { type OnMount } from "@monaco-editor/react";
import type * as monaco from "monaco-editor";
import type React from "react";
import { useEffect, useRef } from "react";

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

interface EditorCanvasProps {
	code: string;
	onChange: (newCode: string) => void;
	geminiCursor: CursorData | null;
	pendingEdits: DiffChunk[] | null;
	onEditsApplied: () => void;
}

export const EditorCanvas: React.FC<EditorCanvasProps> = ({
	code,
	onChange,
	geminiCursor,
	pendingEdits,
	onEditsApplied,
}) => {
	const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
	const monacoRef = useRef<typeof monaco | null>(null);
	const decorationsRef = useRef<string[]>([]);
	const widgetRef = useRef<monaco.editor.IContentWidget | null>(null);

	const handleEditorDidMount: OnMount = (editor, monacoInstance) => {
		editorRef.current = editor;
		monacoRef.current = monacoInstance;

		// Define custom styling for Player 2 cursor decoration
		monacoInstance.editor.defineTheme("gemini-dark", {
			base: "vs-dark",
			inherit: true,
			rules: [
				{ token: "comment", foreground: "6b7280", fontStyle: "italic" },
				{ token: "keyword", foreground: "c084fc" },
				{ token: "string", foreground: "34d399" },
				{ token: "number", foreground: "fbbf24" },
			],
			colors: {
				"editor.background": "#0f172a",
				"editor.lineHighlightBackground": "#1e293b55",
				"editorCursor.foreground": "#38bdf8",
			},
		});

		monacoInstance.editor.setTheme("gemini-dark");
	};

	// 1. Render Gemini Player 2 Cursor and Line Highlight
	useEffect(() => {
		const editor = editorRef.current;
		const monacoInstance = monacoRef.current;
		if (!editor || !monacoInstance || !geminiCursor) return;

		const { line, ch, tag } = geminiCursor;

		// Apply glowing line decoration
		const newDecorations: monaco.editor.IModelDeltaDecoration[] = [
			{
				range: new monacoInstance.Range(line, 1, line, 1),
				options: {
					isWholeLine: true,
					className: "gemini-line-highlight",
					glyphMarginClassName: "gemini-glyph-icon",
				},
			},
		];

		decorationsRef.current = editor.deltaDecorations(
			decorationsRef.current,
			newDecorations,
		);

		// Update or create Gemini Player 2 Cursor Content Widget
		if (widgetRef.current) {
			editor.removeContentWidget(widgetRef.current);
		}

		const widgetNode = document.createElement("div");
		widgetNode.className = "gemini-player2-cursor-widget";
		widgetNode.innerHTML = `
      <div class="gemini-caret"></div>
      <div class="gemini-pill-tag">
        <span class="sparkle">✦</span> ${tag || "Gemini (Player 2)"}
      </div>
    `;

		const contentWidget: monaco.editor.IContentWidget = {
			getId: () => "gemini.player2.cursor",
			getDomNode: () => widgetNode,
			getPosition: () => ({
				position: { lineNumber: line, column: ch },
				preference: [
					monacoInstance.editor.ContentWidgetPositionPreference.EXACT,
				],
			}),
		};

		widgetRef.current = contentWidget;
		editor.addContentWidget(contentWidget);
		editor.revealLineInCenterIfOutsideViewport(line);

		return () => {
			if (widgetRef.current) {
				editor.removeContentWidget(widgetRef.current);
				widgetRef.current = null;
			}
		};
	}, [geminiCursor]);

	// 2. Surgical Diff Execution (Preserves user cursor and undo history)
	useEffect(() => {
		const editor = editorRef.current;
		const monacoInstance = monacoRef.current;
		if (
			!editor ||
			!monacoInstance ||
			!pendingEdits ||
			pendingEdits.length === 0
		)
			return;

		const model = editor.getModel();
		const monacoEdits: monaco.editor.IIdentifiedSingleEditOperation[] =
			pendingEdits.map((chunk) => {
				const startCol = chunk.start_col || 1;
				const endCol =
					chunk.end_col && chunk.end_col > 1
						? chunk.end_col
						: (model?.getLineMaxColumn(chunk.end_line) ?? 1000);

				return {
					range: new monacoInstance.Range(
						chunk.start_line,
						startCol,
						chunk.end_line,
						endCol,
					),
					text: chunk.new_text,
					forceMoveMarkers: true,
				};
			});

		// Apply surgical edit without blowing away user focus
		editor.executeEdits("gemini-player-2", monacoEdits);
		editor.pushUndoStop();
		onEditsApplied();
	}, [pendingEdits, onEditsApplied]);

	return (
		<div className="relative w-full h-full rounded-xl overflow-hidden border border-slate-800 shadow-2xl bg-[#0f172a]">
			<div className="flex items-center justify-between px-4 py-2 bg-slate-900/90 border-b border-slate-800 text-xs text-slate-400 select-none">
				<div className="flex items-center gap-2">
					<span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse"></span>
					<span className="font-mono font-semibold text-slate-200">
						breakout.js
					</span>
					<span className="text-[10px] bg-cyan-950/80 border border-cyan-800/60 text-cyan-300 px-1.5 py-0.5 rounded font-mono">
						Live Mirror Active
					</span>
				</div>
				<div className="flex items-center gap-3">
					{geminiCursor && (
						<span className="flex items-center gap-1 text-cyan-400 font-mono text-[11px]">
							<span className="inline-block w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping"></span>
							Gemini at Ln {geminiCursor.line}, Col {geminiCursor.ch}
						</span>
					)}
				</div>
			</div>
			<div className="w-full h-[calc(100%-36px)]">
				<Editor
					height="100%"
					defaultLanguage="javascript"
					value={code}
					onChange={(val) => onChange(val || "")}
					onMount={handleEditorDidMount}
					options={{
						fontSize: 14,
						fontFamily: "JetBrains Mono, Menlo, monospace",
						minimap: { enabled: false },
						scrollBeyondLastLine: false,
						smoothScrolling: true,
						cursorBlinking: "smooth",
						cursorSmoothCaretAnimation: "on",
						renderLineHighlight: "all",
						padding: { top: 12 },
					}}
				/>
			</div>
		</div>
	);
};
