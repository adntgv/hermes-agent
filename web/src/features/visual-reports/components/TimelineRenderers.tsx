import { CalendarDays } from "lucide-react";
import { ReportCard } from "./ReportCard";
import type { GanttModule, TimelineModule } from "../types";

const statusClass: Record<string, string> = {
  todo: "border-border bg-muted/30",
  active: "border-primary/70 bg-primary/10",
  blocked: "border-destructive/60 bg-destructive/10",
  done: "border-success/60 bg-success/10",
};

function dateMs(value: string) {
  return new Date(value + "T00:00:00").getTime();
}

export function TimelineRenderer({ module }: { module: TimelineModule }) {
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <ol className="space-y-3">
        {module.items.map((item) => (
          <li key={item.id} className="grid grid-cols-[auto_1fr] gap-3">
            <span className={`mt-1 h-3 w-3 rounded-full border ${statusClass[item.status]}`} aria-hidden />
            <div className="min-w-0 border-b border-border/60 pb-3 last:border-b-0">
              <div className="font-medium leading-snug text-foreground">{item.label}</div>
              <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>{item.start}{item.end ? ` to ${item.end}` : ""}</span>
                <span>{item.status}</span>
                {item.owner ? <span>{item.owner}</span> : null}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </ReportCard>
  );
}

export function GanttRenderer({ module }: { module: GanttModule }) {
  const start = dateMs(module.start);
  const end = dateMs(module.end);
  const span = Math.max(end - start, 1);
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><CalendarDays className="h-4 w-4" />{module.start} to {module.end}</div>
      <div className="space-y-3">
        {module.items.map((item) => {
          const left = Math.max(0, Math.min(95, ((dateMs(item.start) - start) / span) * 100));
          const width = Math.max(8, Math.min(100 - left, (((dateMs(item.end ?? item.start) - dateMs(item.start)) || 86400000) / span) * 100));
          return (
            <div key={item.id} className="grid grid-cols-1 gap-1 sm:grid-cols-[7rem_1fr] sm:items-center">
              <div className="truncate text-xs text-muted-foreground">{item.lane}</div>
              <div className="relative h-10 rounded-md bg-muted/40">
                <div className={`absolute top-1.5 h-7 rounded-md border px-2 text-xs leading-7 ${statusClass[item.status]}`} style={{ left: `${left}%`, width: `${width}%` }}>
                  <span className="block truncate">{item.label}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </ReportCard>
  );
}
