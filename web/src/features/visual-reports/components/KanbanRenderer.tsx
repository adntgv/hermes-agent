import { Columns3 } from "lucide-react";
import { ReportCard } from "./ReportCard";
import type { KanbanModule } from "../types";

export function KanbanRenderer({ module }: { module: KanbanModule }) {
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><Columns3 className="h-4 w-4" />{module.columns.length} columns</div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {module.columns.map((column) => (
          <section key={column.id} className="min-w-0 rounded-lg border border-border bg-muted/20 p-3" aria-label={column.title}>
            <h3 className="text-sm font-semibold text-foreground">{column.title}</h3>
            <div className="mt-3 space-y-2">
              {column.cards.map((card) => (
                <article key={card.id} className="min-h-11 rounded-md border border-border bg-card p-3 text-sm">
                  <div className="font-medium text-foreground">{card.title}</div>
                  {card.meta ? <div className="mt-1 text-xs text-muted-foreground">{card.meta}</div> : null}
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </ReportCard>
  );
}
