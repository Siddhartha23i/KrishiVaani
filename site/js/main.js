/**
 * KrishiVaani — main.js
 * High-performance vanilla JavaScript.
 * Handles dynamic URLs, Dark/Light theme switching, canvas particle effects,
 * and mobile responsiveness without heavy external dependencies.
 */

/* ── Global Configuration Constants ──────────────────────────
   TODO: Replace TELEGRAM_BOT_URL with your verified bot username.
   TODO: Replace GITHUB_URL with your repository URL.
   ─────────────────────────────────────────────────────────── */
const TELEGRAM_BOT_URL = "https://t.me/KrishiVaaniBot"; // TODO: Set production Telegram bot link
const GITHUB_URL       = "https://github.com/Siddhartha23i/KrishiVaani"; // TODO: Verify repository URL
const DEMO_VIDEO_URL   = ""; // TODO: Add LinkedIn or YouTube demo video URL

/* ── Inject Dynamic Links ───────────────────────────────────── */
document.querySelectorAll("[data-telegram-link]").forEach(el => {
  if (el.tagName === "A") el.href = TELEGRAM_BOT_URL;
});
document.querySelectorAll("[data-github-link]").forEach(el => {
  if (el.tagName === "A") el.href = GITHUB_URL;
});

/* ── Theme Switcher (Dark / Light Mode) ─────────────────────── */
(function initTheme() {
  const themeToggle = document.getElementById("theme-toggle");
  const themeStateText = document.getElementById("theme-state-text");
  const themeIcon = document.getElementById("theme-icon");

  const SUN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>`;
  const MOON_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("krishivaani-theme", theme);
    if (theme === "light") {
      if (themeStateText) themeStateText.textContent = "Light";
      if (themeIcon) themeIcon.innerHTML = MOON_ICON;
      if (themeToggle) themeToggle.setAttribute("aria-label", "Switch to Dark Mode");
    } else {
      if (themeStateText) themeStateText.textContent = "Dark";
      if (themeIcon) themeIcon.innerHTML = SUN_ICON;
      if (themeToggle) themeToggle.setAttribute("aria-label", "Switch to Light Mode");
    }
  }

  // Check saved theme or default to Dark mode
  const savedTheme = localStorage.getItem("krishivaani-theme") || "dark";
  applyTheme(savedTheme);

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      applyTheme(current === "dark" ? "light" : "dark");
    });
  }
})();

/* ── Nav Scroll Listener ────────────────────────────────────── */
(function initNav() {
  const nav = document.getElementById("main-nav");
  if (!nav) return;

  const onScroll = () => {
    nav.classList.toggle("scrolled", window.scrollY > 30);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
})();

/* ── Interactive Particle Canvas ────────────────────────────── */
(function initParticles() {
  const canvas = document.getElementById("bg-canvas");
  if (!canvas) return;

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    canvas.style.display = "none";
    return;
  }

  const ctx = canvas.getContext("2d");
  let W = 0, H = 0;
  const particles = [];
  const PARTICLE_COUNT = 65;

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function createParticle() {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      r: Math.random() * 1.6 + 0.4,
      alpha: Math.random() * 0.45 + 0.1,
    };
  }

  function init() {
    resize();
    particles.length = 0;
    for (let i = 0; i < PARTICLE_COUNT; i++) particles.push(createParticle());
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    const isLight = document.documentElement.getAttribute("data-theme") === "light";

    // Connecting signal strands
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 125) {
          const alpha = (1 - dist / 125) * (isLight ? 0.08 : 0.09);
          ctx.strokeStyle = isLight ? `rgba(5,150,105,${alpha})` : `rgba(0,220,150,${alpha})`;
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }

    // Nodes
    particles.forEach((p, idx) => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      const color = (idx % 2 === 0)
        ? (isLight ? `rgba(5,150,105,${p.alpha})` : `rgba(0,220,150,${p.alpha})`)
        : (isLight ? `rgba(79,70,229,${p.alpha})` : `rgba(129,140,248,${p.alpha})`);
      ctx.fillStyle = color;
      ctx.fill();

      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = W;
      if (p.x > W) p.x = 0;
      if (p.y < 0) p.y = H;
      if (p.y > H) p.y = 0;
    });

    requestAnimationFrame(draw);
  }

  window.addEventListener("resize", resize, { passive: true });
  init();
  draw();
})();

/* ── Video Click Handler ────────────────────────────────────── */
const videoPoster = document.getElementById("demo-video-box");
if (videoPoster) {
  videoPoster.addEventListener("click", () => {
    if (DEMO_VIDEO_URL) {
      window.open(DEMO_VIDEO_URL, "_blank", "noopener");
    } else {
      alert("TODO: Demo video link will be connected soon! Check back shortly.");
    }
  });
}
