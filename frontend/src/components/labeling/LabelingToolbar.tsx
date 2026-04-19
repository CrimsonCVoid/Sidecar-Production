"use client";

import { Pencil, MousePointer2, Undo2, Redo2, Trash2, Zap } from "lucide-react";
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
}

export function LabelingToolbar({ onSnapPreview, isLoadingPreview }: LabelingToolbarProps) {
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

        {/* Spacer + panel count badge */}
        <div className="flex-1" />
        <Badge variant="secondary" className="text-xs">
          {panels.length} panel{panels.length !== 1 ? "s" : ""}
        </Badge>
      </div>
    </TooltipProvider>
  );
}
