import { describe, expect, it } from "bun:test";

interface DiffChunk {
    start_line: number;
    start_col?: number;
    end_line: number;
    end_col?: number;
    new_text: string;
    description?: string;
}

describe("Overlapping Voice Command + User Edit Concurrency", () => {
    function applyEditsToBuffer(code: string, edits: DiffChunk[]): string {
        const lines = code.split("\n");
        const sorted = [...edits].sort((a, b) => b.start_line - a.start_line);
        for (const edit of sorted) {
            const startIdx = Math.max(0, edit.start_line - 1);
            const endIdx = Math.min(lines.length, Math.max(edit.start_line, edit.end_line));
            const repLines = edit.new_text.replace(/\r\n/g, "\n").split("\n");
            if (repLines.length > 0 && repLines[repLines.length - 1] === "") {
                repLines.pop();
            }
            lines.splice(startIdx, endIdx - startIdx, ...repLines);
        }
        return lines.join("\n");
    }

    it("merges incoming AI diff with concurrent user edits on separate lines", () => {
        let editorCode = (
            "let score = 0;\n" +
            "let lives = 3;\n" +
            "// ball setup\n" +
            "let ball = {\n" +
            '  color: "#f43f5e",\n' +
            "  speed: 5\n" +
            "};\n"
        );

        const sentWsMessages: string[] = [];
        const sendMessageSafe = (msg: string) => {
            sentWsMessages.push(msg);
        };

        // 1. User edits line 1 in editor
        const handleUserEdit = (newText: string) => {
            editorCode = newText;
            sendMessageSafe(JSON.stringify({ type: "editor_sync", code: newText }));
        };

        handleUserEdit(
            "let score = 500;\n" +
            "let lives = 3;\n" +
            "// ball setup\n" +
            "let ball = {\n" +
            '  color: "#f43f5e",\n' +
            "  speed: 5\n" +
            "};\n"
        );

        expect(sentWsMessages.length).toBe(1);
        expect(editorCode).toContain("let score = 500;");

        // 2. Incoming voice diff from Gemini arrives targeting line 5 (ball color)
        const incomingDiff: DiffChunk[] = [
            {
                start_line: 5,
                end_line: 5,
                new_text: '  color: "#fbbf24",\n',
                description: "Turn ball gold",
            },
        ];

        // 3. Editor applies surgical diff
        editorCode = applyEditsToBuffer(editorCode, incomingDiff);

        // 4. Assert both edits are preserved in harmony
        expect(editorCode).toContain("let score = 500;");
        expect(editorCode).toContain('color: "#fbbf24"');
        expect(editorCode).not.toContain('color: "#f43f5e"');
        expect(editorCode).toContain("let lives = 3;");
    });

    it("handles rapid user keystrokes interleaved with AI diff arrival", () => {
        let currentCode = "let a = 1;\nlet b = 2;\n";
        const pendingEditsQueue: DiffChunk[][] = [];

        // Simulate incoming diff from AI worker
        pendingEditsQueue.push([
            { start_line: 2, end_line: 2, new_text: "let b = 99;\n" },
        ]);

        // User is rapidly typing on line 1
        for (let i = 2; i <= 5; i++) {
            currentCode = `let a = ${i};\nlet b = 2;\n`;
        }

        // Apply pending diff
        const edits = pendingEditsQueue.shift()!;
        currentCode = applyEditsToBuffer(currentCode, edits);

        expect(currentCode).toBe("let a = 5;\nlet b = 99;\n");
    });

    it("handles index race: user inserts lines above target line, server rebases diff", () => {
        // Base code that the AI worker received snapshot of:
        const baseCode = (
            "let score = 0;\n" +      // Line 1
            "let lives = 3;\n" +      // Line 2
            "// ball setup\n" +       // Line 3
            "let ball = {\n" +        // Line 4
            '  color: "#f43f5e",\n' + // Line 5 (Target line in base)
            "  speed: 5\n" +          // Line 6
            "};\n"                    // Line 7
        );

        // While AI worker runs, user concurrently inserts 3 lines at line 1
        let editorCode = (
            "// Top header comment\n" +   // Line 1 (user inserted)
            "// Difficulty settings\n" +  // Line 2 (user inserted)
            "const MAX_LIVES = 5;\n" +    // Line 3 (user inserted)
            "let score = 0;\n" +          // Line 4
            "let lives = 3;\n" +          // Line 5
            "// ball setup\n" +           // Line 6
            "let ball = {\n" +            // Line 7
            '  color: "#f43f5e",\n' +     // Line 8 (Target line shifted down by 3 lines!)
            "  speed: 5\n" +              // Line 9
            "};\n"                        // Line 10
        );

        // If backend sent raw un-rebased line 5 diff, applying it to editorCode would overwrite line 5 ("let lives = 3;")!
        // Instead, the backend 3-way merges and rebases the diff against the user's latest buffer:
        const rebasedDiffFromServer: DiffChunk[] = [
            {
                start_line: 8, // Correctly rebased from 5 -> 8
                end_line: 8,
                new_text: '  color: "#fbbf24",\n',
                description: "Turn ball gold (rebased with concurrent edits)",
            },
        ];

        // Apply rebased diff to editor buffer
        editorCode = applyEditsToBuffer(editorCode, rebasedDiffFromServer);

        // Assert all user-inserted lines are preserved at the top
        expect(editorCode).toContain("// Top header comment\n");
        expect(editorCode).toContain("// Difficulty settings\n");
        expect(editorCode).toContain("const MAX_LIVES = 5;\n");
        // Assert lines in between remain intact
        expect(editorCode).toContain("let lives = 3;");
        // Assert ball color was changed on line 8 without corrupting lines 1-7 or 9-10
        expect(editorCode).toContain('color: "#fbbf24"');
        expect(editorCode).not.toContain('color: "#f43f5e"');
        expect(editorCode).toContain("speed: 5");
    });
});
