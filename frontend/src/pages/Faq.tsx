export default function FaqPage() {
  const faqs: { q: string; a: string }[] = [
    { q: "How do I make a song?", a: "Open Create, describe the music you want (genre, mood, tempo, instruments), optionally add lyrics, pick a model under Quality, then Generate. Your results appear under Studio › My Tracks." },
    { q: "What models are there, and which should I pick?", a: "Turbo is fast and reliable for any length and is the best default. SFT and XL‑SFT are higher‑fidelity premium models — best for shorter clips (roughly 30–60s) and vocal tracks. XL‑Turbo is a premium fast option. Start with Turbo; try SFT/XL when you want more detail." },
    { q: "How are my tracks organised?", a: "Everything starts in 'My Default Space' (★, always present). Use the ♪ control on any track to Move it to another workspace, and the filter chips above My Tracks to view one space at a time. Create / rename / delete spaces under Studio › Workspaces." },
    { q: "What happens if I delete a workspace?", a: "The tracks are not deleted — they move back to My Default Space. You cannot delete or rename My Default Space." },
    { q: "What are Artist LoRAs / Training?", a: "Train an Artist Profile on your own tracks to get a consistent personal style. Once a profile has an active version, its style is auto‑applied to your new generations (and you can add its style keywords as a prompt). Training runs on a dedicated worker and takes a few minutes." },
    { q: "Do I keep my exact lyrics?", a: "Yes. Lyrics you provide are sung verbatim — the generator never rewrites them. Leaving lyrics blank for a vocal track lets the AI draft them for you first (you can edit before generating)." },
    { q: "How long can a track be?", a: "Up to 10 minutes in principle. Very long single generations can lose quality on the premium models — for long songs, generate a shorter section and extend/repaint rather than one huge take." },
    { q: "How do credits work?", a: "Each generation uses credits by model: Turbo is 1×, premium SFT/XL cost more. Top up or change plan under Pricing. Free accounts have a daily generation limit." },
    { q: "Can I download or share a track?", a: "Per track: WAV/MP3 download, and Share to make it public (visible in Explore). Stems (separated vocals/drums/bass/other) download as a single .zip via Studio › My Tracks › Stems." },
    { q: "A generation failed or sounds wrong — what do I do?", a: "Try again (transient issues self‑retry). If premium audio sounds garbled, switch to Turbo or a shorter duration. If a track shows an error, open its Details for the model/settings used and 'Reuse recipe' to tweak and re‑run." },
  ];
  return (
    <div className="page">
      <div className="card" style={{ maxWidth: 800, margin: "0 auto" }}>
        <h1>Frequently asked questions</h1>
        <p className="sub">How to use OpenAudioLab's generation, models, workspaces, artist training, and credits.</p>
        <div style={{ display: "grid", gap: 8, marginTop: 14 }}>
          {faqs.map((f) => (
            <details key={f.q} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "10px 14px" }}>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>{f.q}</summary>
              <p className="sub" style={{ marginTop: 8, marginBottom: 0, color: "var(--text, inherit)", overflowWrap: "anywhere" }}>{f.a}</p>
            </details>
          ))}
        </div>
        <p className="sub" style={{ marginTop: 16 }}>
          Still stuck? <a className="link" href="/pricing">Contact support</a>.
        </p>
      </div>
    </div>
  );
}
