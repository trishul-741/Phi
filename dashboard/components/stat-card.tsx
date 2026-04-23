export function StatCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | number;
  tone?: "default" | "safe" | "suspicious" | "malicious" | "needs_review";
}) {
  const toneClass =
    tone === "safe"
      ? "border-safe/25"
      : tone === "suspicious"
        ? "border-suspicious/25"
        : tone === "needs_review"
          ? "border-sky-400/25"
        : tone === "malicious"
          ? "border-malicious/25"
          : "border-line/70";

  return (
    <div className={`rounded-[24px] border bg-white/5 p-5 ${toneClass}`}>
      <div className="text-sm uppercase tracking-[0.14em] text-slate-400">{label}</div>
      <div className="mt-3 text-3xl font-semibold text-white">{value}</div>
    </div>
  );
}
