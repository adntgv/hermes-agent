import type { VisualReportSpec } from "./types";

export const weeklyPlanVisualReport: VisualReportSpec = {
  version: "visual-report/v1",
  id: "weekly-visual-reports-plan",
  title: "Weekly visual reports implementation plan",
  description: "Grounded sample showing every registered visual report module using one data-driven spec.",
  updatedAt: "2026-07-11",
  accessibilityLabel: "Weekly visual reports implementation plan capability gallery",
  modules: [
    { id: "metric-scope", type: "metric", title: "Bounded slice", label: "registered module types", value: 13, trend: { direction: "flat", label: "architecture-owned elsewhere" }, accessibilityLabel: "Thirteen registered visual module types" },
    { id: "progress-current", type: "progress", title: "Completion progress", label: "Uncompleted implementation tasks", value: 0, max: 100, segments: [{ label: "Done", value: 0 }, { label: "Pending", value: 18 }], accessibilityLabel: "Zero percent complete because sample tasks are uncompleted" },
    { id: "timeline-week", type: "timeline", title: "Weekly timeline", description: "Milestones for the bounded implementation slice.", accessibilityLabel: "Timeline of implementation milestones", items: [
      { id: "inspect", label: "Inspect app structure and test conventions", start: "2026-07-11", status: "todo", owner: "Subagent" },
      { id: "tdd", label: "Write registry and sample tests first", start: "2026-07-11", status: "todo", owner: "Subagent" },
      { id: "renderers", label: "Implement focused renderers and fallbacks", start: "2026-07-12", status: "todo", owner: "Subagent" },
      { id: "verify", label: "Run tests, typecheck, and build", start: "2026-07-13", status: "todo", owner: "Subagent" },
    ] },
    { id: "gantt-week", type: "gantt", title: "Implementation schedule", start: "2026-07-11", end: "2026-07-15", accessibilityLabel: "Gantt schedule for visual reports implementation", items: [
      { id: "g1", lane: "Discovery", label: "Inspect existing app", start: "2026-07-11", end: "2026-07-12", status: "todo" },
      { id: "g2", lane: "Contract", label: "Types and registry", start: "2026-07-12", end: "2026-07-13", status: "todo" },
      { id: "g3", lane: "Experience", label: "Gallery page", start: "2026-07-13", end: "2026-07-14", status: "todo" },
      { id: "g4", lane: "Quality", label: "Tests and build", start: "2026-07-14", end: "2026-07-15", status: "todo" },
    ] },
    { id: "kanban-work", type: "kanban", title: "Task board", accessibilityLabel: "Kanban task board for visual report work", columns: [
      { id: "todo", title: "To do", cards: [{ id: "k1", title: "Define VisualSpec union", meta: "Versioned contract" }, { id: "k2", title: "Build registry manifest", meta: "Prompt-ready metadata" }] },
      { id: "doing", title: "Doing", cards: [{ id: "k3", title: "Render all modules through registry", meta: "No hardcoded layout" }] },
      { id: "done", title: "Done", cards: [] },
    ] },
    { id: "priority", type: "priority_matrix", title: "Priority matrix", xLabel: "impact", yLabel: "urgency", accessibilityLabel: "Priority matrix for renderer capabilities", items: [
      { id: "p1", label: "Registry", x: 0.92, y: 0.86, quadrant: "high impact high urgency" },
      { id: "p2", label: "Mobile overflow", x: 0.82, y: 0.72, quadrant: "high impact" },
      { id: "p3", label: "Three fallback", x: 0.58, y: 0.48, quadrant: "medium" },
      { id: "p4", label: "Chart polish", x: 0.44, y: 0.56, quadrant: "medium" },
    ] },
    { id: "dependencies", type: "dependency_graph", title: "Dependency graph", accessibilityLabel: "Dependencies between implementation tasks", nodes: [
      { id: "types", label: "Types" }, { id: "registry", label: "Registry" }, { id: "sample", label: "Sample" }, { id: "page", label: "Page" }, { id: "tests", label: "Tests" }
    ], edges: [
      { from: "types", to: "registry" }, { from: "types", to: "sample" }, { from: "registry", to: "page" }, { from: "sample", to: "page" }, { from: "registry", to: "tests" }
    ] },
    { id: "flow", type: "flow", title: "Render flow", accessibilityLabel: "Visual report render flow", steps: [
      { id: "spec", label: "Receive VisualSpec", detail: "Data only" },
      { id: "filter", label: "Search and filter", detail: "Mobile controls" },
      { id: "lookup", label: "Registry lookup", detail: "Renderer metadata" },
      { id: "fallback", label: "Graceful fallback", detail: "Unsupported or rich media unavailable" },
    ] },
    { id: "comparison", type: "comparison_table", title: "Capability comparison", accessibilityLabel: "Comparison table of renderer capabilities", columns: ["Mobile", "Fallback", "Primary use"], rows: [
      { id: "c1", label: "Chart", values: ["SVG scales to width", "Visible data list", "Trends and quantities"] },
      { id: "c2", label: "Canvas network", values: ["Fixed height responsive canvas", "Static edge list", "Relationship map"] },
      { id: "c3", label: "Three scene", values: ["Contained card", "Text object list", "Spatial hierarchy"] },
    ] },
    { id: "chart-load", type: "chart", title: "Estimated task load", kind: "bar", valueLabel: "tasks", accessibilityLabel: "Bar chart of estimated task load", data: [
      { label: "Types", value: 2 }, { label: "Registry", value: 3 }, { label: "Renderers", value: 7 }, { label: "Page", value: 3 }, { label: "Tests", value: 3 }
    ] },
    { id: "canvas-network", type: "canvas_network", title: "Canvas network", accessibilityLabel: "Canvas network connecting report modules", nodes: [
      { id: "a", label: "Spec", x: 0.18, y: 0.50 }, { id: "b", label: "Registry", x: 0.48, y: 0.24 }, { id: "c", label: "Gallery", x: 0.78, y: 0.50 }, { id: "d", label: "Fallbacks", x: 0.48, y: 0.78 }
    ], edges: [{ from: "a", to: "b" }, { from: "b", to: "c" }, { from: "b", to: "d" }, { from: "d", to: "c" }] },
    { id: "three-scene", type: "three_scene", title: "Three scene", accessibilityLabel: "Three dimensional capability scene", objects: [
      { id: "cube-spec", label: "Spec cube", size: 0.8, position: [-1.4, 0, 0] }, { id: "cube-registry", label: "Registry cube", size: 1, position: [0, 0.3, 0] }, { id: "cube-page", label: "Page cube", size: 0.7, position: [1.4, -0.2, 0] }
    ] },
    { id: "details-all", type: "details", title: "Detailed implementation tasks", accessibilityLabel: "Detailed uncompleted tasks for the weekly plan", sections: [
      { id: "d1", title: "Contract and registry", content: ["Create web/src/features/visual-reports/types.ts with a versioned VisualSpec discriminated union.", "Create registry metadata for every renderer type including mode, Telegram fallback support, and accessibility summaries.", "Expose a manifest that future LLM prompts can inspect without importing renderer components."] },
      { id: "d2", title: "Renderers", content: ["Build focused metric, progress, timeline, gantt, kanban, priority matrix, graph, flow, table, chart, canvas, three scene, and details renderers.", "Keep essential meaning visible without canvas or WebGL interaction.", "Use responsive one-column defaults and progressively enhance to multi-column desktop layouts."] },
      { id: "d3", title: "Page and verification", content: ["Create a searchable and filterable /visual-reports capability gallery.", "Wire route into App.tsx with discoverable navigation only through the existing sidebar pattern.", "Run registry tests, app tests, typecheck, and production build from web."] },
    ] },
  ],
};
