import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { toast } from "../components/Toast";

interface Sheet {
  categories: { name: string; tags: string[] }[];
  lora_tags: string[];
}

export default function StylesPage() {
  const sheet = useQuery({
    queryKey: ["styles-cheatsheet"],
    queryFn: () => api.get<Sheet>("/api/v1/styles/cheatsheet"),
  });

  const copy = (tag: string) => {
    navigator.clipboard?.writeText(tag).then(
      () => toast(`Copied "${tag}" — paste into the Style field`),
      () => toast(tag)
    );
  };

  return (
    <div className="container" style={{ paddingTop: 28 }}>
      <div className="card" style={{ padding: 26 }}>
        <h1 style={{ margin: "0 0 6px" }}>Styles cheat sheet</h1>
        <p style={{ color: "var(--muted)", marginTop: 0 }}>
          Click any tag to copy it, then paste it into the Style field when creating a song.
        </p>
        {sheet.data?.lora_tags && sheet.data.lora_tags.length > 0 && (
          <div className="field" style={{ marginBottom: 18 }}>
            <label>Trained style models</label>
            <div className="cheat-tags">
              {sheet.data.lora_tags.map((t) => (
                <button key={t} className="btn chip chip-lora" onClick={() => copy(t)}>{t}</button>
              ))}
            </div>
          </div>
        )}
        {(sheet.data?.categories || []).map((cat) => (
          <div className="field" key={cat.name} style={{ marginBottom: 16 }}>
            <label>{cat.name}</label>
            <div className="cheat-tags">
              {cat.tags.map((t) => (
                <button key={t} className="btn" onClick={() => copy(t)}>{t}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
