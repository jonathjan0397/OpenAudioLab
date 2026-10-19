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
| Simple creator | One prompt box with optional title and minimal controls | `done` | Keep draft persistence and AI actions stable across themes. |
| Advanced creator | Lyrics, style, title, instrumental, duration, seed, variations | `partial` | Add user-controlled duration and expose seed controls where useful. |
| AI songwriting assistant | Draft, rewrite, humanize, title, style suggestions | `done` | Monitor LLM latency and keep locked fields respected. |
| Approved lyrics path | User-approved lyrics reach generation unchanged | `done` | Preserve lyrics hash and origin in job records. |
| Artist profiles | Named public/private creator identity | `done` | Add delete/rename polish and profile validation. |
| Artist pages | Public page with avatar, bio, tracks, follows, stats | `done` | Improve personalized presentation and discovery links. |
| Discovery | Randomized or personalized community feed | `partial` | Add discovery mode and remove static fallback tiles. |
| Style models | Trained style adapters selectable or auto-applied | `done` | Continue admin LoRA pipeline and tag matching. |
| Custom voices | Artist-specific voice identity, not only style | `research` | Document capability gap until real voice hardware evidence exists. |
| Stems | Export separated stems for a generated track | `partial` | Expose stem status and mixer progress in Studio. |
| Credits and billing | Verified payments, top-ups, subscriptions, ledger | `done` | Monitor Stripe webhook coverage and reconcile refunds manually when needed. |
| Admin accountability | Jobs, workers, credits, errors, pricing, audit | `partial` | Fix pagination, raw fetch handling, and billing truthfulness. |
| Themes | Multiple visual identities with shared business logic | `done` | Preserve Neon Studio, Open Canvas, Analog Soul, Signal Lab. |
| Voice training evidence | Hardware run proves voice identity | `research` | Run a dedicated voice dataset after style batch completes. |

## Immediate Milestone 2 Priorities
1. Done: make the creator a reliable unified workspace: persistent draft, separate description/styles, AI rewrite actions, undo/history, and locked fields.
2. Done: make artist management visible to signed-in users: create/edit profile, avatar, public/private, curated songs.
3. Make discovery feel real: randomized or personalized public feed, fewer static placeholders.
4. Done: make billing/admin trustworthy: production mock-grant guard, payment/invoice/refund event records, admin billing mode, and admin pagination are in place.
5. Keep voice training honest: current LoRAs are style adapters unless a real voice run proves otherwise.
