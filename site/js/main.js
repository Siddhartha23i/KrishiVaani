/**
 * KrishiVaani — main.js
 * Vanilla JS. No dependencies.
 */

/* ── Config ─────────────────────────────────────────────────
   TODO: Replace TELEGRAM_BOT_URL with your actual bot link.
         e.g. "https://t.me/KrishiVaaniBot"
   ─────────────────────────────────────────────────────────── */
const TELEGRAM_BOT_URL = "https://t.me/KrishiVaaniBot"; // TODO: update this URL
const GITHUB_URL       = "https://github.com/Siddhartha23i/KrishiVaani"; // placeholder

/* ── Inject dynamic links ───────────────────────────────────── */
document.querySelectorAll("[data-telegram-link]").forEach(el => {
  if (el.tagName === "A") el.href = TELEGRAM_BOT_URL;
});
document.querySelectorAll("[data-github-link]").forEach(el => {
  if (el.tagName === "A") el.href = GITHUB_URL;
});

/* ── Nav scroll state ───────────────────────────────────────── */
(function initNav() {
  const nav = document.getElementById("main-nav");
  if (!nav) return;

  const onScroll = () => {
    nav.classList.toggle("scrolled", window.scrollY > 40);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
})();

/* ── Particle canvas background ─────────────────────────────── */
(function initParticles() {
  const canvas = document.getElementById("bg-canvas");
  if (!canvas) return;

  /* Respect reduced motion */
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    canvas.style.display = "none";
    return;
  }

  const ctx = canvas.getContext("2d");
  let W = 0, H = 0;

  const PARTICLE_COUNT = 70;
  const particles = [];

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function randomParticle() {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.25,
      vy: (Math.random() - 0.5) * 0.25,
      r: Math.random() * 1.4 + 0.3,
      alpha: Math.random() * 0.4 + 0.05,
    };
  }

  function init() {
    resize();
    particles.length = 0;
    for (let i = 0; i < PARTICLE_COUNT; i++) particles.push(randomParticle());
  }

  /* Soft blue-green palette matching accent colors */
  const COLOR = ["rgba(0,220,150,", "rgba(99,102,241,", "rgba(56,189,248,"];

  function draw() {
    ctx.clearRect(0, 0, W, H);

    /* Draw connection lines between nearby particles */
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 130) {
          const alpha = (1 - dist / 130) * 0.07;
          ctx.strokeStyle = `rgba(0,220,150,${alpha})`;
          ctx.lineWidth = 0.5;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }

    /* Draw particles */
    particles.forEach((p, i) => {
      const color = COLOR[i % COLOR.length];
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = color + p.alpha + ")";
      ctx.fill();

      /* Move */
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = W;
      if (p.x > W) p.x = 0;
      if (p.y < 0) p.y = H;
      if (p.y > H) p.y = 0;
    });

    requestAnimationFrame(draw);
  }

  window.addEventListener("resize", () => { resize(); }, { passive: true });
  init();
  draw();
})();

/* ── Scroll-reveal (IntersectionObserver) ───────────────────── */
(function initScrollReveal() {
  const THRESHOLD = 0.15;

  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el = entry.target;
        const delay = el.dataset.delay ?? "0";
        el.style.transitionDelay = delay + "ms";
        el.classList.add("visible");
        observer.unobserve(el);
      }
    });
  }, { threshold: THRESHOLD });

  document.querySelectorAll(".pipeline-step, .trust-card").forEach(el => {
    observer.observe(el);
  });
})();

/* ── Pipeline step stagger delays ───────────────────────────── */
document.querySelectorAll(".pipeline-step").forEach((el, i) => {
  el.dataset.delay = i * 80;
});
document.querySelectorAll(".trust-card").forEach((el, i) => {
  el.dataset.delay = i * 100;
});

