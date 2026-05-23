export default function LyricsFormattingGuide() {
  return (
    <div style={{ background: "#f8f9fa", border: "1px solid #e9ecef", borderRadius: "6px", padding: "12px", fontSize: "13px", color: "#555" }}>
      <strong style={{ fontSize: "14px" }}>Lyrics Formatting Guide</strong>
      <p style={{ margin: "8px 0 4px" }}>For best results, format your lyrics with clear section labels like <code>[Verse 1]</code>, <code>[Pre-Chorus]</code>, <code>[Chorus]</code>, <code>[Bridge]</code>, and <code>[Outro]</code>.</p>
      <ul style={{ margin: "4px 0", paddingLeft: "20px" }}>
        <li>Keep each sung line on its own line</li>
        <li>Avoid giant paragraphs</li>
        <li>Put performance notes in brackets only when needed</li>
        <li>Custom lyrics are passed through exactly as written</li>
      </ul>
    </div>
  );
}
