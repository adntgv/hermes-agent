import { useEffect, useRef } from "react";
import { Network } from "lucide-react";
import { ReportCard } from "./ReportCard";
import type { CanvasNetworkModule } from "../types";

export function CanvasNetworkRenderer({ module }: { module: CanvasNetworkModule }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);
      const styles = getComputedStyle(document.documentElement);
      const midground = styles.getPropertyValue("--midground-base").trim() || styles.getPropertyValue("--color-foreground").trim() || "currentColor";
      ctx.strokeStyle = midground;
      ctx.fillStyle = midground;
      ctx.lineWidth = 1.5;
      for (const edge of module.edges) {
        const from = module.nodes.find((node) => node.id === edge.from);
        const to = module.nodes.find((node) => node.id === edge.to);
        if (!from || !to) continue;
        ctx.beginPath();
        ctx.moveTo(from.x * rect.width, from.y * rect.height);
        ctx.lineTo(to.x * rect.width, to.y * rect.height);
        ctx.stroke();
      }
      for (const node of module.nodes) {
        const x = node.x * rect.width;
        const y = node.y * rect.height;
        ctx.beginPath();
        ctx.arc(x, y, 9, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillText(node.label, x + 12, y + 4);
      }
    };

    draw();
    const resizeObserver = new ResizeObserver(draw);
    resizeObserver.observe(canvas);
    return () => resizeObserver.disconnect();
  }, [module.edges, module.nodes]);

  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><Network className="h-4 w-4" />Canvas network with accessible static fallback</div>
      <canvas ref={canvasRef} className="h-56 w-full rounded-lg border border-border bg-muted/20" aria-hidden />
      <div className="mt-3 rounded-md border border-border p-3 text-sm">
        <div className="font-medium text-foreground">Canvas unavailable fallback</div>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
          {module.edges.map((edge) => <li key={`${edge.from}-${edge.to}`}>{module.nodes.find((node) => node.id === edge.from)?.label ?? edge.from} to {module.nodes.find((node) => node.id === edge.to)?.label ?? edge.to}</li>)}
        </ul>
      </div>
    </ReportCard>
  );
}
