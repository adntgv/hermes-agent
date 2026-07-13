import { ListChecks, Table2 } from "lucide-react";
import { ReportCard } from "./ReportCard";
import type { ComparisonTableModule, DetailsModule } from "../types";

export function ComparisonTableRenderer({ module }: { module: ComparisonTableModule }) {
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><Table2 className="h-4 w-4" />Comparison table</div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr><th className="px-3 py-2">Item</th>{module.columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}</tr>
          </thead>
          <tbody>
            {module.rows.map((row) => (
              <tr key={row.id} className="border-t border-border">
                <th className="px-3 py-3 font-medium text-foreground">{row.label}</th>
                {row.values.map((value, index) => <td key={`${row.id}-${module.columns[index] ?? index}`} className="px-3 py-3 text-muted-foreground">{value}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ReportCard>
  );
}

export function DetailsRenderer({ module }: { module: DetailsModule }) {
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel} className="md:col-span-2 xl:col-span-3">
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><ListChecks className="h-4 w-4" />Detailed implementation tasks</div>
      <div className="space-y-3">
        {module.sections.map((section, index) => (
          <details key={section.id} className="rounded-lg border border-border bg-muted/20 p-3" open={index === 0}>
            <summary className="min-h-11 cursor-pointer select-none py-2 text-sm font-medium text-foreground">{section.title}</summary>
            <ul className="mt-2 list-disc space-y-2 pl-5 text-sm text-muted-foreground">
              {section.content.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </details>
        ))}
      </div>
    </ReportCard>
  );
}
