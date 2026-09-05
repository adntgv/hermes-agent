import { Fragment } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import VisualReportsPage from "@/pages/VisualReportsPage";
import { renderVisualModule, visualReportRegistry, visualReportRegistryManifest } from "./registry";
import { weeklyPlanVisualReport } from "./sample";
import type { VisualModule, VisualModuleType } from "./types";

const REQUIRED_TYPES: VisualModuleType[] = [
  "metric",
  "progress",
  "timeline",
  "gantt",
  "kanban",
  "priority_matrix",
  "dependency_graph",
  "flow",
  "comparison_table",
  "chart",
  "canvas_network",
  "three_scene",
  "details",
];

describe("visual report registry", () => {
  it("exposes manifest entries for every required visual module type", () => {
    expect(Object.keys(visualReportRegistry).sort()).toEqual([...REQUIRED_TYPES].sort());
    expect(visualReportRegistryManifest.map((entry) => entry.type).sort()).toEqual(
      [...REQUIRED_TYPES].sort(),
    );
    for (const entry of visualReportRegistryManifest) {
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.rendererMode === "rich" || entry.rendererMode === "telegram-fallback").toBe(true);
      expect(entry.accessibilitySummary.length).toBeGreaterThan(0);
    }
  });

  it("keeps manifest JSON and renderer map type sets identical", () => {
    expect(new Set(visualReportRegistryManifest.map((entry) => entry.type))).toEqual(
      new Set(Object.keys(visualReportRegistry)),
    );
  });

  it("renders a graceful fallback for unknown visual module types", () => {
    const unknownModule = {
      id: "unknown-module",
      type: "unknown_type",
      title: "Unknown module",
      accessibilityLabel: "Unknown module fallback",
    } as unknown as VisualModule;

    const markup = renderToStaticMarkup(renderVisualModule(unknownModule));

    expect(markup).toContain("Unsupported visual module");
    expect(markup).toContain("unknown_type");
  });

  it("keeps the sample report fully registry-driven", () => {
    const registered = new Set(Object.keys(visualReportRegistry));
    expect(weeklyPlanVisualReport.version).toBe("visual-report/v1");
    expect(weeklyPlanVisualReport.modules.length).toBeGreaterThanOrEqual(REQUIRED_TYPES.length);
    expect(new Set(weeklyPlanVisualReport.modules.map((module) => module.type))).toEqual(
      new Set(REQUIRED_TYPES),
    );
    expect(
      weeklyPlanVisualReport.modules.every((module) => registered.has(module.type)),
    ).toBe(true);
  });

  it("server-renders every sample module through the registry", () => {
    const markup = renderToStaticMarkup(
      <>{weeklyPlanVisualReport.modules.map((module) => <Fragment key={module.id}>{renderVisualModule(module)}</Fragment>)}</>,
    );

    expect(markup).toContain("Bounded slice");
    expect(markup).toContain("Canvas unavailable fallback");
    expect(markup).toContain("WebGL fallback");
    expect(markup).toContain("Detailed implementation tasks");
  });

  it("server-renders the gallery page shell", () => {
    const markup = renderToStaticMarkup(<VisualReportsPage />);

    expect(markup).toContain("Weekly visual reports implementation plan");
    expect(markup).toContain("Registry-driven capability gallery");
  });
});
