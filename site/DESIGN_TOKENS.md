# KrishiVaani — Design Tokens

Extracted and refined for KrishiVaani: deep-tech dark aesthetic (default) with full light mode support.
Engineered for high contrast, accessibility, and smooth transitions.

## Color Palette

### Dark Mode (Default)
| Token | CSS Variable | Value | Usage |
|---|---|---|---|
| Background base | `--bg-base` | `#0a0a0f` | Main canvas |
| Background deep | `--bg-deep` | `#06060a` | Deep contrast section background |
| Surface 1 | `--surface-1` | `#12121c` | Elevated card & node background |
| Surface 2 | `--surface-2` | `#1a1a2c` | Secondary pill / nested card background |
| Surface glass | `--surface-glass` | `rgba(16, 16, 30, 0.75)` | Glassmorphism panels (nav, cards) |
| Border dim | `--border-dim` | `rgba(255, 255, 255, 0.10)` | Baseline container borders |
| Border glow | `--border-glow` | `rgba(0, 230, 153, 0.45)` | Active & hover glow borders |
| Accent primary | `--accent-primary` | `#00dc96` | Primary CTAs, highlights, step 1-2 |
| Accent secondary | `--accent-secondary` | `#818cf8` | Secondary highlights, routing, tech tags |
| Accent tertiary | `--accent-tertiary` | `#38bdf8` | Live data & weather accents |
| Accent warning | `--accent-warning` | `#fbbf24` | Guardrail alert & referral accents |
| Glow primary | `--glow-primary` | `rgba(0, 220, 150, 0.25)` | Luminous button/node shadow |
| Glow secondary | `--glow-secondary` | `rgba(129, 140, 248, 0.25)`| Luminous node shadow |
| Text primary | `--text-primary` | `#f8fafc` | High-contrast headings |
| Text secondary | `--text-secondary` | `#cbd5e1` | Legible descriptive copy |
| Text muted | `--text-muted` | `#94a3b8` | Metadata, timestamps, captions |

### Light Mode
| Token | CSS Variable | Value | Usage |
|---|---|---|---|
| Background base | `--bg-base` | `#f8fafc` | Main canvas |
| Background deep | `--bg-deep` | `#f1f5f9` | Deep contrast section background |
| Surface 1 | `--surface-1` | `#ffffff` | Elevated card & node background |
| Surface 2 | `--surface-2` | `#e2e8f0` | Secondary pill / nested card background |
| Surface glass | `--surface-glass` | `rgba(255, 255, 255, 0.85)` | Glassmorphism panels |
| Border dim | `--border-dim` | `rgba(15, 23, 42, 0.12)` | Baseline container borders |
| Border glow | `--border-glow` | `rgba(5, 150, 105, 0.45)` | Active & hover glow borders |
| Accent primary | `--accent-primary` | `#059669` | Primary CTAs, highlights |
| Accent secondary | `--accent-secondary` | `#4f46e5` | Secondary highlights |
| Accent tertiary | `--accent-tertiary` | `#0284c7` | Live data & weather accents |
| Accent warning | `--accent-warning` | `#d97706` | Guardrail alert & referral accents |
| Glow primary | `--glow-primary` | `rgba(5, 150, 105, 0.20)` | Button/node shadow |
| Glow secondary | `--glow-secondary` | `rgba(79, 70, 229, 0.18)` | Secondary shadow |
| Text primary | `--text-primary` | `#0f172a` | High-contrast headings |
| Text secondary | `--text-secondary` | `#334155` | Legible descriptive copy |
| Text muted | `--text-muted` | `#64748b` | Metadata, timestamps, captions |

## Typography

| Token | CSS Variable | Value |
|---|---|---|
| Font display | `--font-display` | `'Inter', system-ui, -apple-system, sans-serif` |
| Font telugu | `--font-telugu` | `'Noto Sans Telugu', 'Mandali', 'Gautami', sans-serif` |
| Font mono | `--font-mono` | `'JetBrains Mono', 'Fira Code', 'Consolas', monospace` |
| Size xs | `--text-xs` | `0.75rem` (12px) |
| Size sm | `--text-sm` | `0.875rem` (14px) |
| Size base | `--text-base` | `1rem` (16px) |
| Size lg | `--text-lg` | `1.125rem` (18px) |
| Size xl | `--text-xl` | `1.25rem` (20px) |
| Size 2xl | `--text-2xl` | `1.5rem` (24px) |
| Size 3xl | `--text-3xl` | `2rem` (32px) |
| Size 4xl | `--text-4xl` | `clamp(2rem, 5vw, 2.75rem)` |
| Size 5xl | `--text-5xl` | `clamp(2.5rem, 7vw, 3.75rem)` |

## Spacing & Layout

| Token | CSS Variable | Value |
|---|---|---|
| Section padding Y | `--section-py` | `clamp(4rem, 8vw, 7rem)` |
| Container max | `--container-max` | `1180px` |
| Container padding | `--container-px` | `clamp(1rem, 5vw, 2.5rem)` |
| Card radius | `--radius-card` | `16px` |
| Button radius | `--radius-btn` | `10px` |
| Pill radius | `--radius-pill` | `999px` |

## Motion & Keyframes

| Animation | Duration | Easing | Notes |
|---|---|---|---|
| Signal line flow | `3s infinite` | `linear` | Animated SVG stroke / gradient flow |
| Card fade-up | `600ms` | `cubic-bezier(0.16, 1, 0.3, 1)` | Scroll-triggered intersection observer |
| Button pulse | `2.5s infinite`| `ease-in-out` | Luminous glow pulse on Telegram CTA |
| Live dot blink | `1.5s infinite`| `ease-in-out` | Active Telegram status indicator |
| Theme switch | `250ms` | `ease` | Color transitions on theme toggle |
