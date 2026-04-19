"use client";

import { use, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { toast } from "sonner";
import { useLabelerStore } from "@/stores/labeler-store";
import { getLabels, saveLabels, snapPreview, ApiError } from "@/lib/api";
import { initErrorCapture } from "@/lib/errors";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { LabelingHeader } from "@/components/labeling/LabelingHeader";
import { LabelingToolbar } from "@/components/labeling/LabelingToolbar";

const HillshadeCanvas = dynamic(
  () =>
    import("@/components/canvas/HillshadeCanvas").then((m) => ({
      default: m.HillshadeCanvas,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="flex-1 flex items-center justify-center text-zinc-500">
        Loading canvas...
      </div>
    ),
  },
);

export default function LabelingPage({
  params,
}: {
  params: Promise<{ sampleId: string }>;
}) {
  const { sampleId } = use(params);
  const loadPanels = useLabelerStore((s) => s.loadPanels);
  const isSaving = useLabelerStore((s) => s.isSaving);
  const isLoadingPreview = useLabelerStore((s) => s.isLoadingPreview);

  // Register keyboard shortcuts
  useKeyboardShortcuts();

  // Load saved labels on mount
  useEffect(() => {
    async function loadLabels() {
      try {
        const data = await getLabels(sampleId);
        loadPanels(data.panels);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          // No labels yet -- empty state is fine
          return;
        }
        toast.error(
          "Could not load labels. The sample may not exist or the server is unreachable.",
        );
      }
    }
    loadLabels();
  }, [sampleId, loadPanels]);

  // Initialize error capture
  useEffect(() => {
    const cleanup = initErrorCapture(sampleId);
    return cleanup;
  }, [sampleId]);

  // Save labels handler
  const handleSave = async () => {
    const { panels, setIsSaving } = useLabelerStore.getState();
    if (panels.length === 0) return;
    setIsSaving(true);
    try {
      const result = await saveLabels(sampleId, panels);
      toast.success(`Labels saved (${result.panel_count} panels)`);
    } catch (err) {
      toast.error("Save failed. Check your connection and try again.");
    } finally {
      setIsSaving(false);
    }
  };

  // Snap preview handler
  const handleSnapPreview = async () => {
    const {
      panels,
      snapPreview: currentPreview,
      setSnapPreview,
      setIsLoadingPreview,
    } = useLabelerStore.getState();

    // Toggle off if already showing
    if (currentPreview) {
      setSnapPreview(null);
      return;
    }

    if (panels.length < 2) {
      toast.error(
        "Snap preview failed. Ensure at least 2 panels are labeled, then try again.",
      );
      return;
    }

    setIsLoadingPreview(true);
    try {
      const result = await snapPreview({ panels });
      setSnapPreview({
        features: result.feature_graph.features,
        snappedPolygons: result.snapped_polygons,
      });
      toast.success(
        `Snap preview: ${result.feature_graph.features.length} features detected`,
      );
    } catch (err) {
      toast.error(
        "Snap preview failed. Ensure at least 2 panels are labeled, then try again.",
      );
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const [showHeatmap, setShowHeatmap] = useState(false);
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.5);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const handleGeneratePdf = async () => {
    const { panels } = useLabelerStore.getState();
    if (panels.length === 0) {
      toast.error("No panels to generate PDF from. Draw and save labels first.");
      return;
    }
    setIsGeneratingPdf(true);
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/generate-pdf/${sampleId}`, {
        method: "POST",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "PDF generation failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${sampleId.slice(0, 8)}_cutsheets.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("PDF downloaded!");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "PDF generation failed");
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-zinc-950">
      <LabelingHeader
        sampleId={sampleId}
        onSave={handleSave}
        isSaving={isSaving}
        onGeneratePdf={handleGeneratePdf}
        isGeneratingPdf={isGeneratingPdf}
      />
      <LabelingToolbar
        onSnapPreview={handleSnapPreview}
        isLoadingPreview={isLoadingPreview}
        showHeatmap={showHeatmap}
        onToggleHeatmap={() => setShowHeatmap((v) => !v)}
        heatmapOpacity={heatmapOpacity}
        onHeatmapOpacityChange={setHeatmapOpacity}
      />
      <div className="flex-1" data-testid="labeler-canvas">
        <HillshadeCanvas
          sampleId={sampleId}
          showHeatmap={showHeatmap}
          heatmapOpacity={heatmapOpacity}
        />
      </div>
    </div>
  );
}
