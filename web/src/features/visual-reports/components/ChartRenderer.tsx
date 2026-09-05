import { BarChart3 } from "lucide-react";
import { ReportCard } from "./ReportCard";
import type { ChartModule } from "../types";

export function ChartRenderer({ module }: { module: ChartModule }) {
  const max = Math.max(...module.data.map((d) => d.value), 1);
  const total = module.data.reduce((sum, item) => sum + item.value, 0) || 1;
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><BarChart3 className="h-4 w-4" />{module.kind} chart</div>
      {module.kind === "donut" ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-[10rem_1fr] sm:items-center">
          <svg viewBox="0 0 120 120" className="h-40 w-full" role="img" aria-label={module.accessibilityLabel}>
            <circle cx="60" cy="60" r="42" fill="none" stroke="var(--color-muted)" strokeWidth="18" />
            {module.data.map((item, index) => {
              const pct = item.value / total;
              const dash = `${pct * 264} ${264 - pct * 264}`;
              const offset = -module.data.slice(0, index).reduce((sum, d) => sum + (d.value / total) * 264, 0);
              return <circle key={item.label} cx="60" cy="60" r="42" fill="none" stroke={index % 2 ? "var(--series-output-token)" : "var(--series-input-token)"} strokeWidth="18" strokeDasharray={dash} strokeDashoffset={offset} transform="rotate(-90 60 60)" />;
            })}
          </svg>
          <ChartList data={module.data} valueLabel={module.valueLabel} />
        </div>
      ) : (
        <div className="space-y-3">
          <svg viewBox="0 0 320 150" className="h-44 w-full overflow-visible" role="img" aria-label={module.accessibilityLabel}>
            <line x1="28" y1="126" x2="310" y2="126" stroke="var(--color-border)" />
            {module.data.map((item, index) => {
              const x = 34 + index * (260 / Math.max(module.data.length - 1, 1));
              const h = (item.value / max) * 100;
              const y = 126 - h;
              if (module.kind === "bar") return <rect key={item.label} x={x - 9} y={y} width="18" height={h} rx="3" fill="var(--series-output-token)" opacity="0.8" />;
              return <circle key={item.label} cx={x} cy={y} r="4" fill="var(--series-output-token)" />;
            })}
            {module.kind !== "bar" ? <polyline fill={module.kind === "area" ? "color-mix(in srgb, var(--series-output-token) 18%, transparent)" : "none"} stroke="var(--series-output-token)" strokeWidth="2" points={module.data.map((item, index) => `${34 + index * (260 / Math.max(module.data.length - 1, 1))},${126 - (item.value / max) * 100}`).join(" ")} /> : null}
          </svg>
          <ChartList data={module.data} valueLabel={module.valueLabel} />
        </div>
      )}
    </ReportCard>
  );
}

function ChartList({ data, valueLabel }: { data: ChartModule["data"]; valueLabel?: string }) {
  return (
    <dl className="grid grid-cols-1 gap-2 text-sm">
      {data.map((item) => (
        <div key={item.label} className="flex min-h-11 items-center justify-between rounded-md border border-border px-3">
          <dt className="text-muted-foreground">{item.label}</dt>
          <dd className="font-medium text-foreground">{item.value}{valueLabel ? ` ${valueLabel}` : ""}</dd>
        </div>
      ))}
    </dl>
  );
}
