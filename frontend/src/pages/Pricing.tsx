export default function PricingPage() {
  return (
    <main className="page">
      <div className="section-head" style={{ marginTop: 10 }}>
        <h2>Pricing</h2>
        <span className="sub">Simple credits, no surprises</span>
      </div>
      <div className="stat-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        {[
          ["Free", "1,000 credits", ["10 credits per generation", "WAV downloads", "Community sharing"], false],
          ["Creator", "$9 / month", ["5,000 credits / month", "MP3 + WAV exports", "Artist profiles"], true],
          ["Studio", "$29 / month", ["Unlimited-ish credits", "WAV stems", "Priority queue"], false],
        ].map(([name, price, perks, featured]) => (
          <div key={name as string} className="card stat-card" style={featured ? { borderColor: "var(--accent)" } : undefined}>
            <div>
              <div className="label">{name}</div>
              <div className="value" style={{ fontSize: 24 }}>{price}</div>
              <ul style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: 13, color: "var(--muted)" }}>
                {(perks as string[]).map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          </div>
        ))}
      </div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 18 }}>Billing is coming soon — plans are illustrative.</p>
    </main>
  );
}
