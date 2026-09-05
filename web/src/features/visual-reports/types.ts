import type { ReactNode } from "react";

export type VisualSpecVersion = "visual-report/v1";
export type RendererMode = "rich" | "telegram-fallback";

export type VisualModuleType =
  | "metric"
  | "progress"
  | "timeline"
  | "gantt"
  | "kanban"
  | "priority_matrix"
  | "dependency_graph"
  | "flow"
  | "comparison_table"
  | "chart"
  | "canvas_network"
  | "three_scene"
  | "details";

export interface VisualRendererMetadata {
  rendererMode: RendererMode;
  accessibilitySummary: string;
  supportsTelegramFallback: boolean;
}

export interface BaseVisualModule {
  id: string;
  type: VisualModuleType;
  title: string;
  description?: string;
  accessibilityLabel: string;
  renderer?: Partial<VisualRendererMetadata>;
  tags?: string[];
}

export interface MetricModule extends BaseVisualModule {
  type: "metric";
  value: string | number;
  label: string;
  trend?: { direction: "up" | "down" | "flat"; label: string };
}

export interface ProgressModule extends BaseVisualModule {
  type: "progress";
  value: number;
  max: number;
  label: string;
  segments?: Array<{ label: string; value: number }>;
}

export interface TimelineItem {
  id: string;
  label: string;
  start: string;
  end?: string;
  status: "todo" | "active" | "blocked" | "done";
  owner?: string;
}

export interface TimelineModule extends BaseVisualModule {
  type: "timeline";
  items: TimelineItem[];
}

export interface GanttModule extends BaseVisualModule {
  type: "gantt";
  start: string;
  end: string;
  items: Array<TimelineItem & { lane: string }>;
}

export interface KanbanModule extends BaseVisualModule {
  type: "kanban";
  columns: Array<{ id: string; title: string; cards: Array<{ id: string; title: string; meta?: string }> }>;
}

export interface PriorityMatrixModule extends BaseVisualModule {
  type: "priority_matrix";
  xLabel: string;
  yLabel: string;
  items: Array<{ id: string; label: string; x: number; y: number; quadrant?: string }>;
}

export interface GraphNode { id: string; label: string; group?: string }
export interface GraphEdge { from: string; to: string; label?: string }

export interface DependencyGraphModule extends BaseVisualModule {
  type: "dependency_graph";
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface FlowModule extends BaseVisualModule {
  type: "flow";
  steps: Array<{ id: string; label: string; detail?: string }>;
}

export interface ComparisonTableModule extends BaseVisualModule {
  type: "comparison_table";
  columns: string[];
  rows: Array<{ id: string; label: string; values: string[] }>;
}

export type ChartKind = "bar" | "line" | "area" | "donut";
export interface ChartModule extends BaseVisualModule {
  type: "chart";
  kind: ChartKind;
  data: Array<{ label: string; value: number; series?: string }>;
  valueLabel?: string;
}

export interface CanvasNetworkModule extends BaseVisualModule {
  type: "canvas_network";
  nodes: Array<GraphNode & { x: number; y: number }>;
  edges: GraphEdge[];
}

export interface ThreeSceneModule extends BaseVisualModule {
  type: "three_scene";
  objects: Array<{ id: string; label: string; size: number; position: [number, number, number] }>;
}

export interface DetailsModule extends BaseVisualModule {
  type: "details";
  sections: Array<{ id: string; title: string; content: string[] }>;
}

export type VisualModule =
  | MetricModule
  | ProgressModule
  | TimelineModule
  | GanttModule
  | KanbanModule
  | PriorityMatrixModule
  | DependencyGraphModule
  | FlowModule
  | ComparisonTableModule
  | ChartModule
  | CanvasNetworkModule
  | ThreeSceneModule
  | DetailsModule;

export interface VisualReportSpec {
  version: VisualSpecVersion;
  id: string;
  title: string;
  description: string;
  updatedAt: string;
  accessibilityLabel: string;
  modules: VisualModule[];
}

export interface VisualRegistryManifestEntry extends VisualRendererMetadata {
  type: VisualModuleType;
  label: string;
  description: string;
  dataShape: string;
  selectionGuidance: string;
}

export interface VisualRendererEntry<T extends VisualModule = VisualModule> extends VisualRegistryManifestEntry {
  type: T["type"];
  render: (module: T) => ReactNode;
}
