import type { ReactNode } from "react";

export function Card({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return (
    <section className="card metric">
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      {detail ? <span className="metric-detail">{detail}</span> : null}
    </section>
  );
}
