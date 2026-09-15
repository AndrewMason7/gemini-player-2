"""Constants and default starter templates for Gemini Player 2."""

DEFAULT_BREAKOUT_CODE = """// Gemini: Player 2 - Arcade Breakout & Physics Sandbox
const canvas = document.getElementById("gameCanvas");
const ctx = canvas.getContext("2d");

// --- Audio Synthesizer (Web Audio API) ---
let audioCtx = null;
function initAudio() {
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (AudioContextClass) audioCtx = new AudioContextClass();
  }
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume();
  }
}

function playSound(type) {
  if (!audioCtx) return;
  try {
    const now = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);

    if (type === "paddle") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(320, now);
      osc.frequency.exponentialRampToValueAtTime(480, now + 0.08);
      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.08);
      osc.start(now);
      osc.stop(now + 0.08);
    } else if (type === "brick") {
      const pitch = Math.min(880, 440 + game.combo * 40);
      osc.type = "square";
      osc.frequency.setValueAtTime(pitch, now);
      osc.frequency.exponentialRampToValueAtTime(pitch * 1.5, now + 0.06);
      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.06);
      osc.start(now);
      osc.stop(now + 0.06);
    } else if (type === "wall") {
      osc.type = "triangle";
      osc.frequency.setValueAtTime(220, now);
      gain.gain.setValueAtTime(0.1, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.04);
      osc.start(now);
      osc.stop(now + 0.04);
    } else if (type === "lose") {
      osc.type = "sine";
      osc.frequency.setValueAtTime(180, now);
      osc.frequency.exponentialRampToValueAtTime(80, now + 0.15);
      gain.gain.setValueAtTime(0.05, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
      osc.start(now);
      osc.stop(now + 0.15);
    } else if (type === "victory") {
      [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => {
        const o = audioCtx.createOscillator();
        const g = audioCtx.createGain();
        o.connect(g);
        g.connect(audioCtx.destination);
        o.type = "triangle";
        o.frequency.setValueAtTime(f, now + i * 0.08);
        g.gain.setValueAtTime(0.15, now + i * 0.08);
        g.gain.exponentialRampToValueAtTime(0.01, now + i * 0.08 + 0.12);
        o.start(now + i * 0.08);
        o.stop(now + i * 0.08 + 0.12);
      });
    }
  } catch (e) {}
}

// --- Game State & Entities ---
let game = {
  state: "ready", // "ready" | "playing" | "gameover" | "victory"
  score: 0,
  highScore: Number(localStorage.getItem("breakout_hi") || 0),
  lives: 3,
  level: 1,
  combo: 0,
  maxCombo: 0,
  shake: 0
};

let paddle = {
  x: canvas.width / 2 - 45,
  y: canvas.height - 24,
  width: 90,
  height: 12,
  speed: 8,
  dx: 0,
  color: "#38bdf8"
};

let ball = {
  x: canvas.width / 2,
  y: canvas.height - 36,
  radius: 6,
  speed: 5.5,
  dx: 0,
  dy: 0,
  stuck: true,
  color: "#f43f5e",
  trail: []
};

let particles = [];
let floatingTexts = [];

// --- Brick Grid ---
const brickRows = 4;
const brickCols = 7;
const brickWidth = 55;
const brickHeight = 16;
const brickPadding = 8;
const brickOffsetTop = 38;
const brickOffsetLeft = 20;

let bricks = [];
const rowColors = [
  { fill: "#f43f5e", border: "#fda4af", points: 40 },
  { fill: "#fb923c", border: "#fed7aa", points: 30 },
  { fill: "#34d399", border: "#a7f3d0", points: 20 },
  { fill: "#38bdf8", border: "#bae6fd", points: 10 }
];

function initBricks() {
  bricks = [];
  for (let c = 0; c < brickCols; c++) {
    bricks[c] = [];
    for (let r = 0; r < brickRows; r++) {
      const brickX = c * (brickWidth + brickPadding) + brickOffsetLeft;
      const brickY = r * (brickHeight + brickPadding) + brickOffsetTop;
      const colorScheme = rowColors[r % rowColors.length];
      bricks[c][r] = {
        x: brickX,
        y: brickY,
        status: 1,
        color: colorScheme.fill,
        border: colorScheme.border,
        points: colorScheme.points
      };
    }
  }
}
initBricks();

// --- Particle System ---
function spawnExplosion(x, y, color, count = 12) {
  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = Math.random() * 4 + 1.5;
    particles.push({
      x,
      y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      size: Math.random() * 3 + 2,
      color,
      alpha: 1,
      decay: Math.random() * 0.03 + 0.02
    });
  }
}

function spawnFloatingText(text, x, y, color = "#ffffff") {
  floatingTexts.push({
    text,
    x,
    y,
    vy: -1.2,
    alpha: 1,
    color
  });
}

// --- Input Handling ---
const keys = { left: false, right: false };

window.addEventListener("keydown", (e) => {
  initAudio();
  if (e.key === "ArrowLeft" || e.key === "a" || e.key === "A") keys.left = true;
  if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") keys.right = true;

  if (e.key === " " || e.key === "Enter") {
    launchOrRestart();
  }
});

window.addEventListener("keyup", (e) => {
  if (e.key === "ArrowLeft" || e.key === "a" || e.key === "A") keys.left = false;
  if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") keys.right = false;
});

function handlePointer(clientX) {
  initAudio();
  const rect = canvas.getBoundingClientRect();
  const mouseX = (clientX - rect.left) * (canvas.width / rect.width);
  paddle.x = mouseX - paddle.width / 2;
  clampPaddle();
}

canvas.addEventListener("pointermove", (e) => handlePointer(e.clientX));
canvas.addEventListener("pointerdown", (e) => {
  initAudio();
  handlePointer(e.clientX);
  launchOrRestart();
});

function clampPaddle() {
  if (paddle.x < 4) paddle.x = 4;
  if (paddle.x + paddle.width > canvas.width - 4) {
    paddle.x = canvas.width - 4 - paddle.width;
  }
}

function launchOrRestart() {
  if (game.state === "gameover" || game.state === "victory") {
    game.score = 0;
    game.lives = 3;
    game.level = 1;
    game.combo = 0;
    initBricks();
    resetBall();
    game.state = "playing";
    launchBall();
  } else if (ball.stuck) {
    game.state = "playing";
    launchBall();
  }
}

function launchBall() {
  ball.stuck = false;
  const angle = (Math.random() * 0.6 - 0.3) - Math.PI / 2;
  ball.dx = ball.speed * Math.cos(angle);
  ball.dy = ball.speed * Math.sin(angle);
}

function resetBall() {
  ball.stuck = true;
  ball.trail = [];
  ball.x = paddle.x + paddle.width / 2;
  ball.y = paddle.y - ball.radius - 2;
  ball.dx = 0;
  ball.dy = 0;
}

// --- Physics & Updates ---
function update() {
  if (game.state === "gameover") return;

  if (game.shake > 0) game.shake *= 0.9;
  if (game.shake < 0.1) game.shake = 0;

  if (keys.left) paddle.x -= paddle.speed;
  if (keys.right) paddle.x += paddle.speed;
  clampPaddle();

  if (ball.stuck) {
    ball.x = paddle.x + paddle.width / 2;
    ball.y = paddle.y - ball.radius - 2;
  } else {
    ball.trail.push({ x: ball.x, y: ball.y });
    if (ball.trail.length > 5) ball.trail.shift();

    const prevY = ball.y;

    ball.x += ball.dx;
    ball.y += ball.dy;

    // Wall Collisions
    if (ball.x - ball.radius <= 0) {
      ball.x = ball.radius;
      ball.dx = Math.abs(ball.dx);
      playSound("wall");
    } else if (ball.x + ball.radius >= canvas.width) {
      ball.x = canvas.width - ball.radius;
      ball.dx = -Math.abs(ball.dx);
      playSound("wall");
    }

    if (ball.y - ball.radius <= 0) {
      ball.y = ball.radius;
      ball.dy = Math.abs(ball.dy);
      playSound("wall");
    }

    // Paddle Collision
    if (
      ball.dy > 0 &&
      ball.y + ball.radius >= paddle.y &&
      ball.y - ball.radius <= paddle.y + paddle.height &&
      ball.x >= paddle.x - ball.radius &&
      ball.x <= paddle.x + paddle.width + ball.radius
    ) {
      const hitOffset = (ball.x - (paddle.x + paddle.width / 2)) / (paddle.width / 2);
      const clampedHit = Math.max(-0.95, Math.min(0.95, hitOffset));
      const bounceAngle = clampedHit * (Math.PI * 0.35);

      ball.dx = ball.speed * Math.sin(bounceAngle);
      ball.dy = -ball.speed * Math.cos(bounceAngle);
      ball.y = paddle.y - ball.radius - 1;

      game.combo = 0;
      game.shake = 2;
      spawnExplosion(ball.x, paddle.y, paddle.color, 5);
      playSound("paddle");
    }

    // Brick Collisions
    let activeBricks = 0;
    for (let c = 0; c < brickCols; c++) {
      for (let r = 0; r < brickRows; r++) {
        const b = bricks[c][r];
        if (b.status === 1) {
          activeBricks++;
          if (
            ball.x + ball.radius > b.x &&
            ball.x - ball.radius < b.x + brickWidth &&
            ball.y + ball.radius > b.y &&
            ball.y - ball.radius < b.y + brickHeight
          ) {
            b.status = 0;
            activeBricks--;

            if (prevY + ball.radius <= b.y || prevY - ball.radius >= b.y + brickHeight) {
              ball.dy = -ball.dy;
            } else {
              ball.dx = -ball.dx;
            }

            game.combo++;
            if (game.combo > game.maxCombo) game.maxCombo = game.combo;
            const pts = b.points * game.combo;
            game.score += pts;
            if (game.score > game.highScore) {
              game.highScore = game.score;
              localStorage.setItem("breakout_hi", game.highScore);
            }

            game.shake = 4;
            spawnExplosion(b.x + brickWidth / 2, b.y + brickHeight / 2, b.color, 14);
            spawnFloatingText(`+${pts}${game.combo > 1 ? ` (${game.combo}x)` : ""}`, b.x + brickWidth / 2, b.y, b.border);
            playSound("brick");
          }
        }
      }
    }

    // Victory Check / Next Level
    if (activeBricks === 0 && game.state !== "victory") {
      game.state = "victory";
      game.level++;
      game.score += 500;
      ball.speed += 0.5;
      playSound("victory");
      spawnFloatingText("🎉 LEVEL CLEARED! +500", canvas.width / 2, canvas.height / 2, "#fbbf24");
      setTimeout(() => {
        initBricks();
        resetBall();
        game.state = "playing";
        launchBall();
      }, 1800);
    }

    // Floor Fall / Lose Life
    if (ball.y - ball.radius > canvas.height) {
      game.lives--;
      game.combo = 0;
      game.shake = 4;
      playSound("lose");
      resetBall();

      if (game.lives <= 0) {
        game.state = "gameover";
      }
    }
  }

  // Update Particles
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.vy += 0.08;
    p.alpha -= p.decay;
    if (p.alpha <= 0) particles.splice(i, 1);
  }

  // Update Floating Texts
  for (let i = floatingTexts.length - 1; i >= 0; i--) {
    const ft = floatingTexts[i];
    ft.y += ft.vy;
    ft.alpha -= 0.02;
    if (ft.alpha <= 0) floatingTexts.splice(i, 1);
  }
}

// --- Rendering Engine ---
function draw() {
  ctx.save();

  if (game.shake > 0) {
    const ox = (Math.random() - 0.5) * game.shake;
    const oy = (Math.random() - 0.5) * game.shake;
    ctx.translate(ox, oy);
  }

  ctx.clearRect(-10, -10, canvas.width + 20, canvas.height + 20);

  // Background Grid Lines
  ctx.strokeStyle = "rgba(255, 255, 255, 0.03)";
  ctx.lineWidth = 1;
  for (let x = 0; x < canvas.width; x += 30) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height);
    ctx.stroke();
  }

  // Draw Bricks
  for (let c = 0; c < brickCols; c++) {
    for (let r = 0; r < brickRows; r++) {
      const b = bricks[c][r];
      if (b.status === 1) {
        ctx.fillStyle = b.color;
        ctx.shadowColor = b.color;
        ctx.shadowBlur = 6;
        ctx.fillRect(b.x, b.y, brickWidth, brickHeight);

        ctx.strokeStyle = b.border;
        ctx.lineWidth = 1;
        ctx.strokeRect(b.x + 0.5, b.y + 0.5, brickWidth - 1, brickHeight - 1);
      }
    }
  }
  ctx.shadowBlur = 0;

  // Draw Ball Trail
  for (let i = 0; i < ball.trail.length; i++) {
    const t = ball.trail[i];
    const alpha = ((i + 1) / ball.trail.length) * 0.35;
    const r = ball.radius * ((i + 1) / ball.trail.length);
    ctx.beginPath();
    ctx.arc(t.x, t.y, r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(244, 63, 94, ${alpha})`;
    ctx.fill();
  }

  // Draw Ball
  ctx.beginPath();
  ctx.arc(ball.x, ball.y, ball.radius, 0, Math.PI * 2);
  ctx.fillStyle = ball.color;
  ctx.shadowColor = ball.color;
  ctx.shadowBlur = 12;
  ctx.fill();
  ctx.closePath();
  ctx.shadowBlur = 0;

  // Draw Paddle
  ctx.fillStyle = paddle.color;
  ctx.shadowColor = paddle.color;
  ctx.shadowBlur = 10;
  ctx.fillRect(paddle.x, paddle.y, paddle.width, paddle.height);
  ctx.shadowBlur = 0;

  // Draw Particles
  for (const p of particles) {
    ctx.save();
    ctx.globalAlpha = p.alpha;
    ctx.fillStyle = p.color;
    ctx.shadowColor = p.color;
    ctx.shadowBlur = 4;
    ctx.fillRect(p.x, p.y, p.size, p.size);
    ctx.restore();
  }

  // Draw Floating Texts
  for (const ft of floatingTexts) {
    ctx.save();
    ctx.globalAlpha = Math.max(0, ft.alpha);
    ctx.fillStyle = ft.color;
    ctx.font = "bold 12px monospace";
    ctx.textAlign = "center";
    ctx.shadowColor = ft.color;
    ctx.shadowBlur = 8;
    ctx.fillText(ft.text, ft.x, ft.y);
    ctx.restore();
  }

  // Draw HUD
  ctx.fillStyle = "#94a3b8";
  ctx.font = "11px monospace";
  ctx.textAlign = "left";
  ctx.fillText(`SCORE: ${game.score}`, 14, 18);
  ctx.fillText(`HI: ${game.highScore}`, 95, 18);
  ctx.fillText(`LVL: ${game.level}`, 155, 18);

  const hearts = "❤️".repeat(Math.max(0, game.lives));
  ctx.textAlign = "right";
  ctx.fillText(hearts || "💀", canvas.width - 14, 18);

  if (game.combo > 1) {
    ctx.fillStyle = "#fbbf24";
    ctx.font = "bold 11px monospace";
    ctx.textAlign = "center";
    ctx.fillText(`⚡ COMBO x${game.combo}`, canvas.width / 2, 18);
  }

  // Overlays
  if (ball.stuck && game.state === "ready") {
    ctx.fillStyle = "rgba(15, 23, 42, 0.75)";
    ctx.fillRect(canvas.width / 2 - 120, canvas.height / 2 - 20, 240, 40);
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 1;
    ctx.strokeRect(canvas.width / 2 - 120, canvas.height / 2 - 20, 240, 40);

    ctx.fillStyle = "#38bdf8";
    ctx.font = "bold 12px monospace";
    ctx.textAlign = "center";
    ctx.fillText("SPACE or CLICK to Launch Ball", canvas.width / 2, canvas.height / 2 + 5);
  } else if (game.state === "gameover") {
    ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
    ctx.fillRect(canvas.width / 2 - 130, canvas.height / 2 - 35, 260, 70);
    ctx.strokeStyle = "#f43f5e";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(canvas.width / 2 - 130, canvas.height / 2 - 35, 260, 70);

    ctx.fillStyle = "#f43f5e";
    ctx.font = "bold 16px monospace";
    ctx.textAlign = "center";
    ctx.fillText("GAME OVER", canvas.width / 2, canvas.height / 2 - 8);

    ctx.fillStyle = "#cbd5e1";
    ctx.font = "11px monospace";
    ctx.fillText("Press SPACE or CLICK to Retry", canvas.width / 2, canvas.height / 2 + 16);
  }

  ctx.restore();
}

function loop() {
  update();
  draw();
  requestAnimationFrame(loop);
}

loop();
"""

__all__ = ["DEFAULT_BREAKOUT_CODE"]
