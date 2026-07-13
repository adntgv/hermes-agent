import { useMemo, useState } from "react";
import { Filter, Search, Shapes } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { renderVisualModule, visualReportRegistryManifest } from "@/features/visual-reports/registry";
import { weeklyPlanVisualReport } from "@/features/visual-reports/sample";
import type { RendererMode, VisualModuleType } from "@/features/visual-reports/types";

const ALL_TYPES = "all" as const;
const ALL_MODES = "all" as const;

export default function VisualReportsPage() {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<VisualModuleType | typeof ALL_TYPES>(ALL_TYPES);
  const [modeFilter, setModeFilter] = useState<RendererMode | typeof ALL_MODES>(ALL_MODES);
  const manifestByType = useMemo(() => new Map(visualReportRegistryManifest.map((entry) => [entry.type, entry])), []);
  const filteredModules = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return weeklyPlanVisualReport.modules.filter((module) => {
      const manifest = manifestByType.get(module.type);
      const matchesQuery = !normalized || [module.title, module.description, module.type, manifest?.label, ...(module.tags ?? [])].filter(Boolean).join(" ").toLowerCase().includes(normalized);
      const matchesType = typeFilter === ALL_TYPES || module.type === typeFilter;
      const matchesMode = modeFilter === ALL_MODES || manifest?.rendererMode === modeFilter;
      return matchesQuery && matchesType && matchesMode;
    });
  }, [manifestByType, modeFilter, query, typeFilter]);

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-col gap-4 overflow-x-hidden px-0 pb-8 sm:gap-6" aria-labelledby="visual-reports-title">
      <section className="rounded-xl border border-border bg-card/70 p-4 sm:p-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground"><Shapes className="h-4 w-4" />Registry-driven capability gallery</div>
            <h1 id="visual-reports-title" className="text-2xl font-semibold leading-tight text-foreground sm:text-3xl">{weeklyPlanVisualReport.title}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground sm:text-base">{weeklyPlanVisualReport.description}</p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm md:w-64">
            <Stat label="Modules" value={weeklyPlanVisualReport.modules.length} />
            <Stat label="Visible" value={filteredModules.length} />
          </div>
        </div>
      </section>

      <Card className="border-border bg-card/80">
        <CardContent className="space-y-3 p-3 sm:p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_12rem_12rem]">
            <label className="relative min-w-0">
              <span className="sr-only">Search modules</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input className="min-h-11 w-full rounded-md border border-input bg-background-base py-2 pl-10 pr-3 text-sm text-foreground outline-none focus:ring-1 focus:ring-ring" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search modules" />
            </label>
            <label>
              <span className="sr-only">Filter by type</span>
              <select className="min-h-11 w-full rounded-md border border-input bg-background-base px-3 text-sm text-foreground" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as VisualModuleType | typeof ALL_TYPES)}>
                <option value={ALL_TYPES}>All types</option>
                {visualReportRegistryManifest.map((entry) => <option key={entry.type} value={entry.type}>{entry.label}</option>)}
              </select>
            </label>
            <label>
              <span className="sr-only">Filter by renderer mode</span>
              <select className="min-h-11 w-full rounded-md border border-input bg-background-base px-3 text-sm text-foreground" value={modeFilter} onChange={(event) => setModeFilter(event.target.value as RendererMode | typeof ALL_MODES)}>
                <option value={ALL_MODES}>All modes</option>
                <option value="rich">Rich</option>
                <option value="telegram-fallback">Telegram fallback</option>
              </select>
            </label>
          </div>
          <nav aria-label="Visual report sections" className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
            {filteredModules.map((module) => (
              <a key={module.id} href={`#${module.id}`} className="inline-flex min-h-11 shrink-0 items-center rounded-full border border-border px-3 text-xs text-muted-foreground hover:text-foreground focus:outline-none focus:ring-1 focus:ring-ring">
                {manifestByType.get(module.type)?.label ?? module.type}
              </a>
            ))}
          </nav>
        </CardContent>
      </Card>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label={weeklyPlanVisualReport.accessibilityLabel}>
        {filteredModules.map((module) => (
          <div id={module.id} key={module.id} className="min-w-0 scroll-mt-20">
            {renderVisualModule(module)}
          </div>
        ))}
      </section>

      {filteredModules.length === 0 ? (
        <div className="rounded-lg border border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
          <Filter className="mx-auto mb-2 h-5 w-5" />No visual report modules match the current filters.
          <div className="mt-3"><Button className="min-h-11" onClick={() => { setQuery(""); setTypeFilter(ALL_TYPES); setModeFilter(ALL_MODES); }}>Clear filters</Button></div>
        </div>
      ) : null}
    </main>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg border border-border bg-muted/20 p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="text-xl font-semibold text-foreground">{value}</div></div>;
}
