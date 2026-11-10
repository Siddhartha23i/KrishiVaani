# KrishiVaani — Design Tokens

Extracted and adapted from the visual style of siddhidynamics.in (dark deep-tech premium aesthetic).
Our own colors, content, and assets — no copied assets.

## Color Palette

| Token | CSS Variable | Value | Usage |
|---|---|---|---|
| Background base | `--bg-base` | `#0a0a0f` | Page background |
| Background deep | `--bg-deep` | `#06060a` | Darkest sections |
| Surface 1 | `--surface-1` | `#111118` | Card backgrounds |
| Surface 2 | `--surface-2` | `#1a1a2a` | Elevated surfaces |
| Surface glass | `--surface-glass` | `rgba(16,16,32,0.6)` | Glassmorphism panels |
| Border dim | `--border-dim` | `rgba(255,255,255,0.07)` | Subtle card borders |
| Border glow | `--border-glow` | `rgba(0,220,160,0.25)` | Accent borders on hover |
| Accent primary | `--accent-primary` | `#00dc96` | CTA buttons, highlights (teal-green for agriculture) |
| Accent secondary | `--accent-secondary` | `#6366f1` | Secondary highlights, pipeline icons |
| Accent tertiary | `--accent-tertiary` | `#38bdf8` | Info accents |
| Glow primary | `--glow-primary` | `rgba(0,220,150,0.18)` | Box-shadow glow |
| Glow secondary | `--glow-secondary` | `rgba(99,102,241,0.18)` | Secondary glow |
| Text primary | `--text-primary` | `#f0f0f8` | Headings, main text |
| Text secondary | `--text-secondary` | `#9494b0` | Body, descriptions |
| Text muted | `--text-muted` | `#5a5a78` | Captions, placeholders |
| Danger | `--danger` | `#f43f5e` | Warnings |

## Typography

| Token | CSS Variable | Value |
|---|---|---|
| Font display | `--font-display` | `'Inter', system-ui, -apple-system, sans-serif` |
| Font mono | `--font-mono` | `'JetBrains Mono', 'Fira Code', monospace` |
| Size xs | `--text-xs` | `0.75rem` |
| Size sm | `--text-sm` | `0.875rem` |
| Size base | `--text-base` | `1rem` |
| Size lg | `--text-lg` | `1.125rem` |
| Size xl | `--text-xl` | `1.25rem` |
| Size 2xl | `--text-2xl` | `1.5rem` |
| Size 3xl | `--text-3xl` | `2rem` |
| Size 4xl | `--text-4xl` | `2.75rem` |
| Size 5xl | `--text-5xl` | `3.75rem` |
| Letter spacing tight | `--tracking-tight` | `-0.03em` |
| Letter spacing wide | `--tracking-wide` | `0.08em` |
| Line height relaxed | `--leading-relaxed` | `1.65` |

## Spacing & Layout

| Token | CSS Variable | Value |
|---|---|---|
| Section padding Y | `--section-py` | `clamp(4rem, 8vw, 7rem)` |
| Container max | `--container-max` | `1180px` |
| Container padding | `--container-px` | `clamp(1rem, 5vw, 2.5rem)` |
| Card radius | `--radius-card` | `16px` |
| Button radius | `--radius-btn` | `10px` |
| Icon size | `--icon-size` | `48px` |

## Shadows & Blurs

| Token | CSS Variable | Value |
|---|---|---|
| Card shadow | `--shadow-card` | `0 1px 2px rgba(0,0,0,0.5), 0 0 0 1px var(--border-dim)` |
| Glow shadow | `--shadow-glow` | `0 0 32px var(--glow-primary)` |
| Blur glass | `--blur-glass` | `12px` |

## Animations

| Name | Easing | Duration | Notes |
|---|---|---|---|
| Fade-up reveal | `cubic-bezier(0.16,1,0.3,1)` | 600ms | Scroll-reveal items |
| Hero title | `cubic-bezier(0.16,1,0.3,1)` | 900ms staggered | Letter/word reveal |
| Button pulse | ease-in-out | 2.5s infinite | CTA glow pulse |
| Pipeline flow | ease | 400ms stagger | Step sequential entrance |
| Particle drift | linear | 20–40s infinite | Background canvas particles |
| Hover card lift | ease | 200ms | translateY(-4px) |
| Nav blur appear | ease | 150ms | backdrop-filter on scroll |
| Live dot blink | ease-in-out | 1.5s infinite | Telegram live indicator |
