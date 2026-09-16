import { describe, expect, it } from "bun:test";
import { readFileSync } from "fs";
import { resolve } from "path";

describe("Game Edits - Ball Color Transformation", () => {
    // Read the canonical DEFAULT_BREAKOUT_CODE from backend/constants.py
    const constantsPath = resolve(import.meta.dir, "../../backend/constants.py");
    const constantsContent = readFileSync(constantsPath, "utf8");
    const match = constantsContent.match(/DEFAULT_BREAKOUT_CODE = """([\s\S]*?)"""/);
    if (!match) {
        throw new Error("Could not extract DEFAULT_BREAKOUT_CODE from backend/constants.py");
    }
    const defaultCode = match[1];

    function applyLineEdits(
        code: string,
        edits: Array<{ start_line: number; end_line: number; new_text: string }>
    ): string {
        const lines = code.split("\n");
        const sorted = [...edits].sort((a, b) => b.start_line - a.start_line);
        for (const edit of sorted) {
            const startIdx = Math.max(0, edit.start_line - 1);
            const endIdx = Math.min(lines.length, Math.max(edit.start_line, edit.end_line));
            const repLines = edit.new_text.replace(/\r\n/g, "\n").split("\n");
            // If new_text ended with newline, split produces trailing empty string
            if (repLines.length > 0 && repLines[repLines.length - 1] === "") {
                repLines.pop();
            }
            lines.splice(startIdx, endIdx - startIdx, ...repLines);
        }
        return lines.join("\n");
    }

    function evaluateGameCode(code: string) {
        const ctx = new Proxy({}, { get: () => () => ({}) });
        const canvas = {
            getContext: () => ctx,
            width: 480,
            height: 320,
            addEventListener: () => {},
        };
        globalThis.document = {
            getElementById: () => canvas,
            addEventListener: () => {},
        } as unknown as Document;
        globalThis.window = { addEventListener: () => {} } as unknown as Window & typeof globalThis;
        globalThis.requestAnimationFrame = () => 0;
        globalThis.localStorage = {
            getItem: () => "0",
            setItem: () => {},
        } as unknown as Storage;

        const runner = new Function(code + "\nreturn { ball, paddle, game };");
        return runner();
    }

    it("DEFAULT_BREAKOUT_CODE initially has crimson ball (#f43f5e)", () => {
        const result = evaluateGameCode(defaultCode);
        expect(result.ball.color).toBe("#f43f5e");
        expect(result.ball.speed).toBe(5.5);
    });

    it("applying surgical diff on line 105 actually turns the ball gold (#fbbf24)", () => {
        const edits = [
            {
                start_line: 105,
                end_line: 105,
                new_text: '  color: "#fbbf24",\n',
            },
        ];

        const editedCode = applyLineEdits(defaultCode, edits);
        expect(editedCode).toContain('color: "#fbbf24"');
        expect(editedCode).not.toContain('color: "#f43f5e"');

        const result = evaluateGameCode(editedCode);
        expect(result.ball.color).toBe("#fbbf24");
        // Verify surrounding ball properties remain untouched
        expect(result.ball.speed).toBe(5.5);
        expect(result.ball.radius).toBe(6);
        expect(result.ball.stuck).toBe(true);
        // Verify paddle and game state still function
        expect(result.paddle.width).toBe(90);
        expect(result.game.state).toBe("ready");
    });
});
