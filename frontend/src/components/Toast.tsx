import { useEffect, useState } from "react";

export function toast(message: string) {
  window.dispatchEvent(new CustomEvent("oal-toast", { detail: message }));
}

export default function Toaster() {
  const [msgs, setMsgs] = useState<{ id: number; msg: string }[]>([]);
  useEffect(() => {
    const handler = (e: Event) => {
      const id = Date.now() + Math.random();
      setMsgs((m) => [...m, { id, msg: (e as CustomEvent).detail }]);
      window.setTimeout(() => setMsgs((m) => m.filter((x) => x.id !== id)), 3500);
    };
    window.addEventListener("oal-toast", handler);
    return () => window.removeEventListener("oal-toast", handler);
  }, []);
  return (
    <div className="toaster">
      {msgs.map((m) => (
        <div key={m.id} className="toast">
          {m.msg}
        </div>
      ))}
    </div>
  );
}
