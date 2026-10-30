"use client";

import { Bounds, OrbitControls, Splat, useBounds, useGLTF, useProgress } from "@react-three/drei";
import { Canvas, useLoader } from "@react-three/fiber";
import { Pause, Play, RotateCcw } from "lucide-react";
import { Component, Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

import type { Twin } from "@/lib/api/types";

import { VIEWER_HEIGHT } from "./twin-viewer-height";

function PointCloud({ url, pointScale }: { url: string; pointScale: number }) {
  const geometry = useLoader(PLYLoader, url);
  const { hasColor, radius } = useMemo(() => {
    geometry.computeBoundingSphere();
    return { hasColor: geometry.hasAttribute("color"), radius: geometry.boundingSphere?.radius ?? 1 };
  }, [geometry]);
  // Point size scales with the model so small reliefs and large tanks both read as solid surfaces.
  const size = radius * 0.006 * pointScale;
  return (
    <points geometry={geometry}>
      <pointsMaterial size={size} sizeAttenuation vertexColors={hasColor} color={hasColor ? "#ffffff" : "#b45309"} />
    </points>
  );
}

function Mesh({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

/** Re-fits the camera whenever `signal` changes (Reset view button). */
function Refit({ signal }: { signal: number }) {
  const bounds = useBounds();
  useEffect(() => {
    if (signal > 0) bounds.refresh().clip().fit();
  }, [bounds, signal]);
  return null;
}

/**
 * Plain DOM overlay rather than drei's <Html>: that mounts a second React root inside the canvas,
 * which React 19 cannot unmount while the Suspense boundary is committing.
 */
function LoadingOverlay() {
  const { active, progress } = useProgress();
  if (!active) return null;
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <span role="status" className="rounded-full bg-white/90 px-3 py-1 text-sm font-semibold text-ink shadow">
        Loading model… {Math.round(progress)}%
      </span>
    </div>
  );
}

class ViewerBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="flex h-full items-center justify-center p-6 text-center text-sm text-white/80">
        This 3D model could not be displayed ({this.state.error.message || "WebGL unavailable"}). The source file
        can still be downloaded below.
      </div>
    );
  }
}

export default function TwinViewer({ twin }: { twin: Twin }) {
  const [autoRotate, setAutoRotate] = useState(
    () => typeof window !== "undefined" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [pointScale, setPointScale] = useState(1);
  const [refit, setRefit] = useState(0);
  const isSplat = twin.format === "splat";
  const isPoints = twin.format === "ply";

  return (
    <figure className="overflow-hidden rounded-[var(--radius-card)] border border-ink/20 bg-ink shadow-[var(--shadow-card)]">
      <div
        className={`${VIEWER_HEIGHT} relative bg-[radial-gradient(ellipse_at_top,#2d4a6e,#0f1d2e)]`}
        role="img"
        aria-label={`Interactive 3D model: ${twin.title}. Drag to orbit, scroll or pinch to zoom.`}
      >
        <ViewerBoundary>
          <Canvas
            dpr={[1, 2]}
            frameloop={autoRotate || isSplat ? "always" : "demand"}
            camera={{ position: [0, 40, 120], fov: 45, near: 0.1, far: 10_000 }}
            gl={{ antialias: true }}
          >
            <ambientLight intensity={1.2} />
            <directionalLight position={[50, 80, 40]} intensity={1.5} />
            <Suspense fallback={null}>
              {isSplat ? (
                <Splat src={twin.url} />
              ) : (
                <Bounds fit clip observe margin={1.15}>
                  {isPoints ? <PointCloud url={twin.url} pointScale={pointScale} /> : <Mesh url={twin.url} />}
                  <Refit signal={refit} />
                </Bounds>
              )}
            </Suspense>
            <OrbitControls makeDefault autoRotate={autoRotate} autoRotateSpeed={0.6} enableDamping />
          </Canvas>
        </ViewerBoundary>
        <LoadingOverlay />
      </div>
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-white/10 px-4 py-3 text-sm text-white/85">
        <button
          type="button"
          onClick={() => setAutoRotate((v) => !v)}
          aria-pressed={autoRotate}
          className="btn btn-ghost px-2 py-1 text-white hover:bg-white/10"
        >
          {autoRotate ? <Pause aria-hidden className="size-4" /> : <Play aria-hidden className="size-4" />}
          {autoRotate ? "Pause rotation" : "Auto-rotate"}
        </button>
        {!isSplat && (
          <button
            type="button"
            onClick={() => setRefit((n) => n + 1)}
            className="btn btn-ghost px-2 py-1 text-white hover:bg-white/10"
          >
            <RotateCcw aria-hidden className="size-4" /> Reset view
          </button>
        )}
        {isPoints && (
          <label className="flex items-center gap-2">
            <span>Point size</span>
            <input
              type="range"
              min={0.4}
              max={3}
              step={0.1}
              value={pointScale}
              onChange={(e) => setPointScale(Number(e.target.value))}
              className="w-28 accent-amber-400"
            />
          </label>
        )}
        <a href={twin.url} download className="ml-auto underline decoration-white/40 underline-offset-2 hover:text-white">
          Download .{twin.format}
        </a>
      </figcaption>
    </figure>
  );
}
