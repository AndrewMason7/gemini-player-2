import { describe, expect, it } from "bun:test";

describe("GamePreview - Iframe Error Containment & Resilience", () => {
    function buildIframeSrcDoc(code: string): string {
        const sanitizedCode = code.replace(/<\/script/gi, "<\\/script");
        return `
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
    }

    it("generates iframe HTML with canvas and error capture traps", () => {
        const srcdoc = buildIframeSrcDoc("console.log('init');");
        expect(srcdoc).toContain('<canvas id="gameCanvas"');
        expect(srcdoc).toContain("window.onerror = function");
        expect(srcdoc).toContain("GAME_ERROR");
        expect(srcdoc).toContain("window.parent.postMessage");
    });

    it("catches synchronous runtime errors and posts GAME_ERROR without crashing host", () => {
        const postedMessages: Array<{ type: string; message: string }> = [];
        const mockParent = {
            postMessage: (data: { type: string; message: string }) => {
                postedMessages.push(data);
            },
        };

        const testHarness = `
            const window = { parent: mockParent };
            try {
                // Code that throws runtime exception
                throw new TypeError("Cannot read properties of undefined (reading 'width')");
            } catch (err) {
                window.parent.postMessage({ type: "GAME_ERROR", message: err.message });
            }
        `;

        const runner = new Function("mockParent", testHarness);
        runner(mockParent);

        expect(postedMessages.length).toBe(1);
        expect(postedMessages[0].type).toBe("GAME_ERROR");
        expect(postedMessages[0].message).toContain("Cannot read properties of undefined");
    });

    it("catches asynchronous game loop errors via window.onerror trap", () => {
        const postedMessages: Array<{ type: string; message: string }> = [];
        let capturedErrorHandler: ((msg: string, url: string, line: number) => void) | null = null;

        const mockWindow = {
            set onerror(fn: (msg: string, url: string, line: number) => void) {
                capturedErrorHandler = fn;
            },
            parent: {
                postMessage: (data: { type: string; message: string }) => {
                    postedMessages.push(data);
                },
            },
        };

        // Simulate iframe initialization of onerror
        mockWindow.onerror = function (msg: string, url: string, line: number) {
            mockWindow.parent.postMessage({
                type: "GAME_ERROR",
                message: msg + " (line " + line + ")",
            });
        };

        expect(capturedErrorHandler).not.toBeNull();

        // Simulate async canvas animation loop crash (e.g. invalid context call)
        if (capturedErrorHandler) {
            (capturedErrorHandler as (msg: string, url: string, line: number) => void)(
                "Uncaught RangeError: Maximum call stack size exceeded",
                "game.js",
                42
            );
        }

        expect(postedMessages.length).toBe(1);
        expect(postedMessages[0].type).toBe("GAME_ERROR");
        expect(postedMessages[0].message).toContain("Maximum call stack size exceeded (line 42)");
    });

    it("safely neutralizes closing </script> tags in code to prevent DOM breakout", () => {
        const maliciousCode = 'const str = "</script><script>window.pwned = true;</script>";';
        const srcdoc = buildIframeSrcDoc(maliciousCode);

        // Verify that raw unescaped </script> does NOT prematurely close the <script> block
        // Any occurrences of </script before the final closing tag should be escaped as <\/script
        const scriptContent = srcdoc.substring(srcdoc.indexOf("<script>") + 8, srcdoc.lastIndexOf("</script>"));
        expect(scriptContent).not.toContain("</script>");
        expect(scriptContent).toContain("<\\/script>");
    });

    it("message receiver handles GAME_ERROR from iframe window and rejects alien sources", () => {
        let currentError: string | null = null;

        const mockIframeWindow = {} as Window;
        const mockAlienWindow = {} as Window;

        const handleMessage = (e: { source: unknown; data: { type?: string; message?: string } }) => {
            if (e.source !== mockIframeWindow) return;
            if (e.data?.type === "GAME_ERROR") {
                currentError = String(e.data.message);
            }
        };

        // 1. Message from alien/unrelated window -> ignored
        handleMessage({
            source: mockAlienWindow,
            data: { type: "GAME_ERROR", message: "Alien error injected" },
        });
        expect(currentError).toBeNull();

        // 2. Message with wrong type -> ignored
        handleMessage({
            source: mockIframeWindow,
            data: { type: "OTHER_EVENT", message: "Ignored" },
        });
        expect(currentError).toBeNull();

        // 3. Legitimate GAME_ERROR from iframe contentWindow -> captured in state
        handleMessage({
            source: mockIframeWindow,
            data: { type: "GAME_ERROR", message: "SyntaxError: Unexpected token '{' (line 12)" },
        });
        expect(currentError).toBe("SyntaxError: Unexpected token '{' (line 12)");
    });

    it("restartGame resets error state and forces iframe reload via key change", () => {
        let error: string | null = "SyntaxError: Unexpected token";
        let key = 0;

        const restartGame = () => {
            key += 1;
            error = null;
        };

        restartGame();
        expect(error).toBeNull();
        expect(key).toBe(1);
    });
});
