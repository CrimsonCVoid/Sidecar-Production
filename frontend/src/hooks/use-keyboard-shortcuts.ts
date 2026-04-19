"use client";

import { useEffect } from "react";
import { useLabelerStore } from "@/stores/labeler-store";

/**
 * Registers global keyboard shortcuts for the labeling page.
 *
 * Shortcuts:
 *  - Cmd+Z / Ctrl+Z       -> Undo (via zundo temporal)
 *  - Cmd+Shift+Z / Ctrl+Shift+Z -> Redo (via zundo temporal)
 *  - Escape               -> Cancel active drawing or deselect panel
 *  - Delete / Backspace   -> Delete selected panel
 *  - D                    -> Switch to draw mode
 *  - S                    -> Switch to select mode
 */
export function useKeyboardShortcuts(): void {
  const mode = useLabelerStore((s) => s.mode);
  const selectedPanelIndex = useLabelerStore((s) => s.selectedPanelIndex);
  const activeDrawing = useLabelerStore((s) => s.activeDrawing);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ignore if user is typing in an input/textarea
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      // Cmd+Shift+Z -> Redo (check before Cmd+Z since Shift+Z includes Z)
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "z") {
        e.preventDefault();
        useLabelerStore.temporal.getState().redo();
        return;
      }

      // Cmd+Z -> Undo
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        useLabelerStore.temporal.getState().undo();
        return;
      }

      // Escape -> Cancel drawing or deselect
      if (e.key === "Escape") {
        e.preventDefault();
        if (activeDrawing) {
          useLabelerStore.getState().cancelDrawing();
        } else {
          useLabelerStore.getState().selectPanel(null);
        }
        return;
      }

      // Delete / Backspace -> Delete selected panel
      if (e.key === "Delete" || e.key === "Backspace") {
        if (selectedPanelIndex !== null) {
          e.preventDefault();
          useLabelerStore.getState().deletePanel(selectedPanelIndex);
        }
        return;
      }

      // D -> Draw mode (only without modifier keys to avoid Cmd+D conflicts)
      if (e.key.toLowerCase() === "d" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        useLabelerStore.getState().setMode("draw");
        return;
      }

      // S -> Select mode (only without modifier keys to avoid Cmd+S conflicts)
      if (e.key.toLowerCase() === "s" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        useLabelerStore.getState().setMode("select");
        return;
      }

      // E -> Edit mode (drag vertices, insert midpoints)
      if (e.key.toLowerCase() === "e" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        useLabelerStore.getState().setMode("edit");
        return;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mode, selectedPanelIndex, activeDrawing]);
}
