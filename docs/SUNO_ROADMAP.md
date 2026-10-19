# Suno Parity Roadmap

Review date: 2026-10-19

Source links:
- Suno product surface: https://suno.com/
- OpenAudioLab architecture: `docs/ARCHITECTURE.md`
- OpenAudioLab artist training notes: `docs/ARTIST_TRAINING.md`

Status legend:
- `done`: present and usable in the current OpenAudioLab app.
- `partial`: present in a limited or internal-only form.
- `gap`: not present or not user-visible enough for parity.
- `research`: needs product/engine evidence before implementation.

| Capability | Suno-style expectation | OpenAudioLab status | Next step |
|---|---|---|---|
| Text-to-song generation | Prompt becomes a full song with vocals or instrumental | `done` | Keep ACE-Step path stable and improve defaults. |
| Simple creator | One prompt box with optional title and minimal controls | `partial` | Persist draft state and separate description from style tags. |
| Advanced creator | Lyrics, style, title, instrumental, duration, seed, variations | `partial` | Unify simple/advanced fields and add locked fields. |
| AI songwriting assistant | Draft, rewrite, humanize, title, style suggestions | `partial` | Add explicit assistant actions and revision history. |
| Approved lyrics path | User-approved lyrics reach generation unchanged | `done` | Preserve lyrics hash and origin in job records. |
| Artist profiles | Named public/private creator identity | `partial` | Add management UI for avatar, sharing, and curated songs. |
| Artist pages | Public page with avatar, bio, tracks, follows, stats | `partial` | Improve personalized presentation and discovery links. |
| Discovery | Randomized or personalized community feed | `partial` | Add discovery mode and remove static fallback tiles. |
| Style models | Trained style adapters selectable or auto-applied | `done` | Continue admin LoRA pipeline and tag matching. |
| Custom voices | Artist-specific voice identity, not only style | `research` | Document capability gap until real voice hardware evidence exists. |
| Stems | Export separated stems for a generated track | `partial` | Expose stem status and mixer progress in Studio. |
| Credits and billing | Verified payments, top-ups, subscriptions, ledger | `gap` | Disable mock grants in production and add payment/invoice records. |
| Admin accountability | Jobs, workers, credits, errors, pricing, audit | `partial` | Fix pagination, raw fetch handling, and billing truthfulness. |
| Themes | Multiple visual identities with shared business logic | `done` | Preserve Neon Studio, Open Canvas, Analog Soul, Signal Lab. |
| Voice training evidence | Hardware run proves voice identity | `research` | Run a dedicated voice dataset after style batch completes. |

## Immediate Milestone 2 Priorities
1. Make the creator a reliable unified workspace: persistent draft, separate description/styles, AI rewrite actions, undo/history, and locked fields.
2. Make artist management visible to signed-in users: create/edit profile, avatar, public/private, curated songs.
3. Make discovery feel real: randomized or personalized public feed, fewer static placeholders.
4. Make billing/admin trustworthy: production mock-grant guard, better ledger/payment references, admin pagination and error handling.
5. Keep voice training honest: current LoRAs are style adapters unless a real voice run proves otherwise.
