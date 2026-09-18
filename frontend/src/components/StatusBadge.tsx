const good = new Set(["healthy", "success", "ready", "normalized", "detected", "ok"]);
const warning = new Set(["warning", "low", "retry", "waiting_for_quota", "discovered", "downloaded"]);
const bad = new Set(["unhealthy", "failed", "not_entitled", "not_found", "blocked", "exhausted", "cooldown"]);

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const normalized = (value ?? "unknown").toLowerCase();
  const tone = good.has(normalized) ? "good" : warning.has(normalized) ? "warn" : bad.has(normalized) ? "bad" : "neutral";
  return <span className={`badge ${tone}`}>{normalized.replaceAll("_", " ")}</span>;
}
