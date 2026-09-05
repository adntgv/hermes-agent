import { useMemo } from "react";
import { Cuboid } from "lucide-react";
import { Canvas } from "@react-three/fiber";
import { ReportCard } from "./ReportCard";
import type { ThreeSceneModule } from "../types";

function SceneObjects({ module }: { module: ThreeSceneModule }) {
  return (
    <>
      <ambientLight intensity={0.8} />
      <pointLight position={[4, 4, 4]} intensity={1} />
      {module.objects.map((object) => (
        <mesh key={object.id} position={object.position}>
          <boxGeometry args={[object.size, object.size, object.size]} />
          <meshStandardMaterial color="#ffe6cb" roughness={0.55} />
        </mesh>
      ))}
    </>
  );
}

function canAttemptWebGL() {
  if (typeof window === "undefined") return false;
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (reduced) return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl") || canvas.getContext("experimental-webgl"));
  } catch {
    return false;
  }
}

export function ThreeSceneRenderer({ module }: { module: ThreeSceneModule }) {
  const webglAvailable = useMemo(() => canAttemptWebGL(), []);
  return (
    <ReportCard title={module.title} description={module.description} accessibilityLabel={module.accessibilityLabel}>
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><Cuboid className="h-4 w-4" />Three scene with reduced-motion fallback</div>
      {webglAvailable ? (
        <div className="h-56 overflow-hidden rounded-lg border border-border bg-muted/20">
          <Canvas camera={{ position: [0, 0, 6], fov: 45 }} frameloop="demand">
            <SceneObjects module={module} />
          </Canvas>
        </div>
      ) : null}
      <div className={webglAvailable ? "sr-only" : "rounded-md border border-border p-3 text-sm"}>
        <div className="font-medium text-foreground">WebGL fallback</div>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
          {module.objects.map((object) => <li key={object.id}>{object.label}: size {object.size}, position {object.position.join(", ")}</li>)}
        </ul>
      </div>
    </ReportCard>
  );
}
