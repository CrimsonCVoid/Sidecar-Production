"use client";

import { use, useEffect } from "react";
import dynamic from "next/dynamic";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { useLabelerStore } from "@/stores/labeler-store";
import { getLabels, ApiError } from "@/lib/api";
import { initErrorCapture } from "@/lib/errors";
import { Badge } from "@/components/ui/badge";

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
  const panels = useLabelerStore((s) => s.panels);
  const loadPanels = useLabelerStore((s) => s.loadPanels);

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

  return (
    <div className="flex flex-col h-screen bg-zinc-950">
      {/* Header (48px) */}
      <div className="h-12 bg-zinc-900 flex items-center px-6 gap-4">
        <button
          onClick={() => window.history.back()}
          className="text-zinc-400 hover:text-white transition-colors"
          aria-label="Go back"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <h1 className="text-xl font-semibold text-white">
          Labeling: {sampleId}
        </h1>
        <div className="ml-auto">
          {/* Save button placeholder -- wired in Plan 04 */}
        </div>
      </div>

      {/* Toolbar (44px) */}
      <div className="h-11 bg-zinc-900 border-b border-zinc-800 flex items-center px-4 gap-2">
        <span className="text-sm text-zinc-400">
          Draw | Select | Undo | Redo | Delete | Snap Preview
        </span>
        <div className="ml-auto">
          <Badge variant="secondary">{panels.length} panels</Badge>
        </div>
      </div>

      {/* Canvas area (flex-1) */}
      <div className="flex-1" data-testid="labeler-canvas">
        <HillshadeCanvas sampleId={sampleId} />
      </div>
    </div>
  );
}
