# KrishiVaani — Marketing Site (`/site`)

One-page marketing website for the KrishiVaani project.
Static HTML + CSS + vanilla JS. No build tools required.

## Run locally

```bash
# Option 1 — open directly in browser
start site/index.html

# Option 2 — local dev server (Python)
cd site
python -m http.server 8080
# then open http://localhost:8080
```

## Deploy

### GitHub Pages
1. Push the repo to GitHub.
2. Go to **Settings → Pages → Source**.
3. Set branch `main`, folder `/site`.
4. The site will be live at `https://<username>.github.io/<repo>/`.

### Netlify
Drag-and-drop the `site/` folder at <https://app.netlify.com/drop>.

### Vercel
```bash
npx vercel site/
```

## Configuration

Open [`js/main.js`](js/main.js) and update the two constants at the top:

```js
// TODO: Replace with your actual Telegram bot link
const TELEGRAM_BOT_URL = "https://t.me/KrishiVaaniBot";

// TODO: Replace with your GitHub repo URL
const GITHUB_URL = "https://github.com/Siddhartha23i/KrishiVaani";
```

## Structure

```
site/
├── index.html            — single-page HTML (semantic, accessible)
├── css/
│   └── styles.css        — all styles; CSS custom properties; mobile-first
├── js/
│   └── main.js           — particles, scroll-reveal, nav scroll state
├── assets/
│   └── icons/            — SVG icons (all inline-safe)
│       ├── farmer.svg    — Step 1: Farmer speaks
│       ├── stt.svg       — Step 2: Speech-to-text
│       ├── router.svg    — Step 3: Intent routing
│       ├── brain.svg     — Step 4: AI reasoning
│       ├── shield.svg    — Step 5: Safety guardrails
│       ├── tts.svg       — Step 6: Text-to-speech
│       ├── voice-reply.svg — Step 7: Delivery
│       ├── verified.svg  — Trust card icon
│       ├── weather.svg   — Trust card icon
│       ├── global.svg    — Trust card icon
│       ├── telegram.svg  — Telegram brand icon
│       └── whatsapp.svg  — WhatsApp brand icon
├── DESIGN_TOKENS.md      — color palette, typography, animation spec
└── README.md             — this file
```

## Constraints

- No tracking scripts.
- No emojis (SVG icons only).
- WhatsApp button is intentionally disabled (coming soon).
- Total page weight target: under 1 MB.
- Respects `prefers-reduced-motion`.
- Does **not** modify `app/`, `tests/`, `Dockerfile`, or other backend files.

