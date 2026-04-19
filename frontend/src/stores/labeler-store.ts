import { create } from "zustand";
import { temporal } from "zundo";

export interface PanelData {
  id: number;
  corners_pix: number[][];
}

export interface SnapPreviewData {
  features: {
    id: number;
    valence: number;
    position_xyz: number[] | null;
    panel_ids: number[];
  }[];
  snappedPolygons: Record<string, number[][]>;
}

interface LabelerState {
  panels: PanelData[];
  activeDrawing: number[][] | null;
  nextPanelId: number;
  mode: "draw" | "select" | "edit";
  selectedPanelIndex: number | null;
  snapPreview: SnapPreviewData | null;
  isSaving: boolean;
  isLoadingPreview: boolean;

  addVertex: (x: number, y: number) => void;
  insertVertex: (panelIndex: number, edgeIndex: number, x: number, y: number) => void;
  moveVertex: (panelIndex: number, vertexIndex: number, x: number, y: number) => void;
  closePolygon: () => void;
  deletePanel: (index: number) => void;
  setMode: (mode: "draw" | "select" | "edit") => void;
  selectPanel: (index: number | null) => void;
  setSnapPreview: (data: SnapPreviewData | null) => void;
  loadPanels: (panels: PanelData[]) => void;
  cancelDrawing: () => void;
  setIsSaving: (v: boolean) => void;
  setIsLoadingPreview: (v: boolean) => void;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare global {
  interface Window {
    __labeler_store?: typeof useLabelerStore;
  }
}

export const useLabelerStore = create<LabelerState>()(
  temporal(
    (set) => ({
      panels: [],
      activeDrawing: null,
      nextPanelId: 0,
      mode: "draw" as "draw" | "select" | "edit",
      selectedPanelIndex: null,
      snapPreview: null,
      isSaving: false,
      isLoadingPreview: false,

      addVertex: (x: number, y: number) =>
        set((state) => ({
          activeDrawing: state.activeDrawing
            ? [...state.activeDrawing, [x, y]]
            : [[x, y]],
          snapPreview: null,
        })),

      insertVertex: (panelIndex: number, edgeIndex: number, x: number, y: number) =>
        set((state) => {
          const panels = state.panels.map((p, i) => {
            if (i !== panelIndex) return p;
            const newCorners = [...p.corners_pix];
            newCorners.splice(edgeIndex + 1, 0, [x, y]);
            return { ...p, corners_pix: newCorners };
          });
          return { panels, snapPreview: null };
        }),

      moveVertex: (panelIndex: number, vertexIndex: number, x: number, y: number) =>
        set((state) => {
          // Find the old position of the dragged vertex
          const oldPos = state.panels[panelIndex].corners_pix[vertexIndex];
          const SHARED_THRESHOLD = 1.0; // pixels — vertices within 1px are considered shared

          // Move matching vertices across ALL panels (shared node behavior)
          const panels = state.panels.map((p) => {
            const newCorners = p.corners_pix.map((c) => {
              const dx = c[0] - oldPos[0];
              const dy = c[1] - oldPos[1];
              if (Math.sqrt(dx * dx + dy * dy) < SHARED_THRESHOLD) {
                return [x, y];
              }
              return c;
            });
            return { ...p, corners_pix: newCorners };
          });
          return { panels, snapPreview: null };
        }),

      closePolygon: () =>
        set((state) => {
          if (!state.activeDrawing || state.activeDrawing.length < 3) {
            return { activeDrawing: null };
          }
          const newPanel: PanelData = {
            id: state.nextPanelId,
            corners_pix: state.activeDrawing,
          };
          return {
            panels: [...state.panels, newPanel],
            activeDrawing: null,
            nextPanelId: state.nextPanelId + 1,
            snapPreview: null,
          };
        }),

      deletePanel: (index: number) =>
        set((state) => ({
          panels: state.panels.filter((_, i) => i !== index),
          selectedPanelIndex: null,
          snapPreview: null,
        })),

      setMode: (mode: "draw" | "select" | "edit") => set({ mode }),

      selectPanel: (index: number | null) =>
        set({ selectedPanelIndex: index }),

      setSnapPreview: (data: SnapPreviewData | null) =>
        set({ snapPreview: data }),

      loadPanels: (panels: PanelData[]) => {
        const maxId =
          panels.length > 0
            ? Math.max(...panels.map((p) => p.id)) + 1
            : 0;
        set({
          panels,
          nextPanelId: maxId,
          activeDrawing: null,
          snapPreview: null,
        });
      },

      cancelDrawing: () => set({ activeDrawing: null }),

      setIsSaving: (v: boolean) => set({ isSaving: v }),

      setIsLoadingPreview: (v: boolean) => set({ isLoadingPreview: v }),
    }),
    {
      partialize: (state) => ({
        panels: state.panels,
        activeDrawing: state.activeDrawing,
        nextPanelId: state.nextPanelId,
      }),
    },
  ),
);

// Expose store for Playwright E2E test inspection (dev only)
if (typeof window !== "undefined") {
  window.__labeler_store = useLabelerStore;
}
