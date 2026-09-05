import { GitBranch, Workflow } from "lucide-react";
import { ReportCard } from "./ReportCard";
import type { DependencyGraphModule, FlowModule, PriorityMatrixModule } from "../types";

export function PriorityMatrixRenderer({ module }: { module: PriorityMatrixModule }) {
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="relative aspect-square min-h-[260px] rounded-lg border border-border bg-muted/20 p-3">
        <div className="absolute inset-x-3 top-1/2 border-t border-border" />
        <div className="absolute inset-y-3 left-1/2 border-l border-border" />
        <span className="absolute bottom-2 left-3 text-xs text-muted-foreground">Low {module.xLabel}</span>
        <span className="absolute bottom-2 right-3 text-xs text-muted-foreground">High {module.xLabel}</span>
        <span className="absolute left-3 top-2 text-xs text-muted-foreground">High {module.yLabel}</span>
        {module.items.map((item) => (
          <div key={item.id} className="absolute max-w-[46%] rounded-md border border-border bg-card px-2 py-1 text-xs shadow-sm" style={{ left: `${Math.min(88, Math.max(4, item.x * 92))}%`, bottom: `${Math.min(88, Math.max(8, item.y * 88))}%` }} title={item.quadrant}>
            {item.label}
          </div>
        ))}
      </div>
    </ReportCard>
  );
}

export function DependencyGraphRenderer({ module }: { module: DependencyGraphModule }) {
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><GitBranch className="h-4 w-4" />Dependency graph as accessible adjacency list</div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {module.nodes.map((node) => {
          const outgoing = module.edges.filter((edge) => edge.from === node.id);
          return (
            <div key={node.id} className="rounded-md border border-border p-3 text-sm">
              <div className="font-medium text-foreground">{node.label}</div>
              <div className="mt-2 text-xs text-muted-foreground">
                {outgoing.length ? outgoing.map((edge) => module.nodes.find((n) => n.id === edge.to)?.label ?? edge.to).join(", ") : "No outgoing dependencies"}
              </div>
            </div>
          );
        })}
      </div>
    </ReportCard>
  );
}

export function FlowRenderer({ module }: { module: FlowModule }) {
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <ol className="grid grid-cols-1 gap-3 md:grid-cols-4">
        {module.steps.map((step, index) => (
          <li key={step.id} className="relative min-h-11 rounded-lg border border-border bg-muted/20 p-3">
            <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"><Workflow className="h-4 w-4" />Step {index + 1}</div>
            <div className="text-sm font-medium text-foreground">{step.label}</div>
            {step.detail ? <div className="mt-1 text-xs text-muted-foreground">{step.detail}</div> : null}
          </li>
        ))}
      </ol>
    </ReportCard>
  );
}
