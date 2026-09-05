import { ChartRenderer } from "./components/ChartRenderer";
import { KanbanRenderer } from "./components/KanbanRenderer";
import { CanvasNetworkRenderer } from "./components/CanvasNetworkRenderer";
import { ThreeSceneRenderer } from "./components/ThreeSceneRenderer";
import { UnsupportedModule } from "./components/ReportCard";
import { MetricRenderer, ProgressRenderer } from "./components/MetricProgressRenderers";
import { GanttRenderer, TimelineRenderer } from "./components/TimelineRenderers";
import { DependencyGraphRenderer, FlowRenderer, PriorityMatrixRenderer } from "./components/MatrixGraphFlowRenderers";
import { ComparisonTableRenderer, DetailsRenderer } from "./components/TableDetailsRenderers";
import manifestJson from "./manifest.json";
import type { ReactNode } from "react";
import type { VisualModule, VisualModuleType, VisualRegistryManifestEntry, VisualRendererEntry } from "./types";

type Registry = { [K in VisualModuleType]: VisualRendererEntry<Extract<VisualModule, { type: K }>> };
type Renderers = { [K in VisualModuleType]: (module: Extract<VisualModule, { type: K }>) => ReactNode };

const renderers: Renderers = {
  metric: (module) => <MetricRenderer module={module} />,
  progress: (module) => <ProgressRenderer module={module} />,
  timeline: (module) => <TimelineRenderer module={module} />,
  gantt: (module) => <GanttRenderer module={module} />,
  kanban: (module) => <KanbanRenderer module={module} />,
  priority_matrix: (module) => <PriorityMatrixRenderer module={module} />,
  dependency_graph: (module) => <DependencyGraphRenderer module={module} />,
  flow: (module) => <FlowRenderer module={module} />,
  comparison_table: (module) => <ComparisonTableRenderer module={module} />,
  chart: (module) => <ChartRenderer module={module} />,
  canvas_network: (module) => <CanvasNetworkRenderer module={module} />,
  three_scene: (module) => <ThreeSceneRenderer module={module} />,
  details: (module) => <DetailsRenderer module={module} />,
};

function assertManifestMatchesRenderers(
  manifest: VisualRegistryManifestEntry[],
  rendererMap: Renderers,
): asserts manifest is VisualRegistryManifestEntry[] {
  const manifestTypes = manifest.map((entry) => entry.type);
  const rendererTypes = Object.keys(rendererMap) as VisualModuleType[];
  const duplicateTypes = manifestTypes.filter((type, index) => manifestTypes.indexOf(type) !== index);
  const missingRenderers = manifestTypes.filter((type) => !(type in rendererMap));
  const missingManifestEntries = rendererTypes.filter((type) => !manifestTypes.includes(type));

  if (duplicateTypes.length || missingRenderers.length || missingManifestEntries.length) {
    throw new Error(
      "Visual report manifest and renderer registry are out of sync: "
      + `duplicate manifest types=${[...new Set(duplicateTypes)].join(",") || "none"}; `
      + `manifest without renderer=${missingRenderers.join(",") || "none"}; `
      + `renderer without manifest=${missingManifestEntries.join(",") || "none"}`,
    );
  }
}

const rawManifest = (manifestJson as { components?: VisualRegistryManifestEntry[] }).components ?? [];
assertManifestMatchesRenderers(rawManifest, renderers);

export const visualReportRegistryManifest: VisualRegistryManifestEntry[] = rawManifest;

export const visualReportRegistry: Registry = Object.fromEntries(
  visualReportRegistryManifest.map((entry) => [
    entry.type,
    {
      ...entry,
      render: renderers[entry.type],
    },
  ]),
) as Registry;

export function renderVisualModule(module: VisualModule): ReactNode {
  const entry = visualReportRegistry[module.type as VisualModuleType];
  if (!entry) return <UnsupportedModule type={String((module as { type?: unknown }).type ?? "unknown")} title={(module as { title?: string }).title} />;
  try {
    return entry.render(module as never);
  } catch (error) {
    return <UnsupportedModule type={`${module.type} (${error instanceof Error ? error.message : "render error"})`} title={module.title} />;
  }
}
