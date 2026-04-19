"use client";

import { Pencil, MousePointer2, Move, Undo2, Redo2, Trash2, Zap, Flame } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useLabelerStore } from "@/stores/labeler-store";

interface LabelingToolbarProps {
  onSnapPreview?: () => void;
  isLoadingPreview?: boolean;
  showHeatmap?: boolean;
  onToggleHeatmap?: () => void;
  heatmapOpacity?: number;
  onHeatmapOpacityChange?: (v: number) => void;
}

export function LabelingToolbar({
  onSnapPreview,
  isLoadingPreview,
  showHeatmap = false,
  onToggleHeatmap,
  heatmapOpacity = 0.5,
  onHeatmapOpacityChange,
}: LabelingToolbarProps) {
  const mode = useLabelerStore((s) => s.mode);
  const setMode = useLabelerStore((s) => s.setMode);
  const selectedPanelIndex = useLabelerStore((s) => s.selectedPanelIndex);
  const panels = useLabelerStore((s) => s.panels);
  const deletePanel = useLabelerStore((s) => s.deletePanel);

  const handleUndo = () => useLabelerStore.temporal.getState().undo();
  const handleRedo = () => useLabelerStore.temporal.getState().redo();
  const handleDelete = () => {
    if (selectedPanelIndex !== null) {
      deletePanel(selectedPanelIndex);
    }
  };

  return (
    <TooltipProvider delay={300}>
      <div className="h-11 bg-zinc-900 border-b border-zinc-800 flex items-center px-4 gap-1 shrink-0">
        {/* Mode buttons */}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant={mode === "draw" ? "default" : "ghost"}
                size="sm"
                onClick={() => setMode("draw")}
                className={mode === "draw" ? "bg-blue-500 hover:bg-blue-600" : ""}
                aria-label="Draw mode"
              >
                <Pencil className="h-4 w-4 mr-1" />
                Draw
              </Button>
            }
          />
          <TooltipContent>Draw mode (D)</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant={mode === "select" ? "default" : "ghost"}
                size="sm"
                onClick={() => setMode("select")}
                className={mode === "select" ? "bg-blue-500 hover:bg-blue-600" : ""}
                aria-label="Select mode"
              >
                <MousePointer2 className="h-4 w-4 mr-1" />
                Select
              </Button>
            }
          />
          <TooltipContent>Select mode (S)</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant={mode === "edit" ? "default" : "ghost"}
                size="sm"
                onClick={() => setMode("edit")}
                className={mode === "edit" ? "bg-amber-500 hover:bg-amber-600" : ""}
                aria-label="Edit mode"
              >
                <Move className="h-4 w-4 mr-1" />
                Edit
              </Button>
            }
          />
          <TooltipContent>Edit mode — drag vertices, click edges to add points (E)</TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="mx-2 h-6" />

        {/* Undo / Redo */}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button variant="ghost" size="sm" onClick={handleUndo} aria-label="Undo">
                <Undo2 className="h-4 w-4 mr-1" />
                Undo
              </Button>
            }
          />
          <TooltipContent>Undo (Cmd+Z)</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger
            render={
              <Button variant="ghost" size="sm" onClick={handleRedo} aria-label="Redo">
                <Redo2 className="h-4 w-4 mr-1" />
                Redo
              </Button>
            }
          />
          <TooltipContent>Redo (Cmd+Shift+Z)</TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="mx-2 h-6" />

        {/* Delete */}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDelete}
                disabled={selectedPanelIndex === null}
                className="text-red-500 hover:text-red-400 disabled:text-zinc-600"
                aria-label="Delete selected panel"
              >
                <Trash2 className="h-4 w-4 mr-1" />
                Delete
              </Button>
            }
          />
          <TooltipContent>Delete selected panel (Delete key)</TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="mx-2 h-6" />

        {/* Snap Preview */}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="ghost"
                size="sm"
                onClick={onSnapPreview}
                disabled={isLoadingPreview || panels.length < 2}
                aria-label="Snap Preview"
              >
                <Zap className="h-4 w-4 mr-1" />
                Snap Preview
              </Button>
            }
          />
          <TooltipContent>Run snap preview on current panels</TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="mx-2 h-6" />

        {/* Heatmap toggle + opacity */}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant={showHeatmap ? "default" : "ghost"}
                size="sm"
                onClick={onToggleHeatmap}
                className={showHeatmap ? "bg-orange-600 hover:bg-orange-700" : ""}
                aria-label="Toggle elevation heatmap"
              >
                <Flame className="h-4 w-4 mr-1" />
                Heatmap
              </Button>
            }
          />
          <TooltipContent>Toggle elevation heatmap overlay</TooltipContent>
        </Tooltip>

        {showHeatmap && (
          <div className="flex items-center gap-2 ml-1">
            <span className="text-xs text-zinc-400">Opacity</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={heatmapOpacity}
              onChange={(e) => onHeatmapOpacityChange?.(parseFloat(e.target.value))}
              className="w-20 h-1 accent-orange-500"
            />
            <span className="text-xs text-zinc-500 w-8">{Math.round(heatmapOpacity * 100)}%</span>
          </div>
        )}

        {/* Spacer + panel count badge */}
        <div className="flex-1" />
        <Badge variant="secondary" className="text-xs">
          {panels.length} panel{panels.length !== 1 ? "s" : ""}
        </Badge>
      </div>
    </TooltipProvider>
  );
}
