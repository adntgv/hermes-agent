import { ArrowDownRight, ArrowRight, ArrowUpRight, Gauge } from "lucide-react";
import { ReportCard } from "./ReportCard";
import type { MetricModule, ProgressModule } from "../types";

export function MetricRenderer({ module }: { module: MetricModule }) {
  const TrendIcon = module.trend?.direction === "up" ? ArrowUpRight : module.trend?.direction === "down" ? ArrowDownRight : ArrowRight;
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="flex min-w-0 items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-3xl font-semibold leading-none text-foreground sm:text-4xl">{module.value}</div>
          <div className="mt-2 text-sm text-muted-foreground">{module.label}</div>
        </div>
        {module.trend ? (
          <div className="flex min-h-11 items-center gap-1.5 rounded-full border border-border px-3 text-sm text-muted-foreground">
            <TrendIcon className="h-4 w-4" />
            {module.trend.label}
          </div>
        ) : null}
      </div>
    </ReportCard>
  );
}

export function ProgressRenderer({ module }: { module: ProgressModule }) {
  const pct = Math.max(0, Math.min(100, Math.round((module.value / Math.max(module.max, 1)) * 100)));
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <Gauge className="h-4 w-4" />
        <span>{module.label}</span>
        <span className="ml-auto font-medium text-foreground">{pct}%</span>
      </div>
      <div className="mt-3 h-3 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={module.value} aria-valuemin={0} aria-valuemax={module.max}>
        <div className="h-full bg-primary transition-[width]" style={{ width: `${pct}%` }} />
      </div>
      {module.segments ? (
        <dl className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {module.segments.map((segment) => (
            <div key={segment.label} className="flex min-h-11 items-center justify-between rounded-md border border-border px-3 text-sm">
              <dt className="text-muted-foreground">{segment.label}</dt>
              <dd className="font-medium text-foreground">{segment.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </ReportCard>
  );
}
