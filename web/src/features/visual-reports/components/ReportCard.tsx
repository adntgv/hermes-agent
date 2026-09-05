import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { cn } from "@/lib/utils";

export function ReportCard({
  title,
  description,
  accessibilityLabel,
  children,
  className,
}: {
  title: string;
  description?: string;
  accessibilityLabel: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("min-w-0 overflow-hidden border-border/80 bg-card/80", className)} aria-label={accessibilityLabel}>
      <CardHeader className="space-y-1 p-4 sm:p-5">
        <CardTitle className="text-base leading-tight text-foreground">{title}</CardTitle>
        {description ? <p className="text-sm leading-snug text-muted-foreground">{description}</p> : null}
      </CardHeader>
      <CardContent className="min-w-0 p-4 pt-0 sm:p-5 sm:pt-0">{children}</CardContent>
    </Card>
  );
}

export function UnsupportedModule({ type, title }: { type: string; title?: string }) {
  return (
    <ReportCard title={title ?? "Unsupported visual module"} accessibilityLabel="Unsupported visual module fallback">
      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <div className="font-medium text-foreground">Unsupported visual module</div>
          <div>Renderer type {type} is not registered yet.</div>
        </div>
      </div>
    </ReportCard>
  );
}
