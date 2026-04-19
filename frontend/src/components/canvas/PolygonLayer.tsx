"use client";

import { Circle, Group, Line, Text } from "react-konva";
import type { PanelData } from "@/stores/labeler-store";
import type { KonvaEventObject } from "konva/lib/Node";

const PANEL_PALETTE = [
  "#06b6d4", "#f97316", "#8b5cf6", "#84cc16",
  "#f43f5e", "#f59e0b", "#14b8a6", "#ec4899",
  "#0ea5e9", "#10b981", "#d946ef", "#6366f1",
  "#64748b", "#a8a29e", "#ef4444", "#3b82f6",
];

interface PolygonLayerProps {
  panels: PanelData[];
  selectedPanelIndex: number | null;
  mode: "draw" | "select" | "edit";
  onSelectPanel: (index: number) => void;
  onMoveVertex?: (panelIndex: number, vertexIndex: number, x: number, y: number) => void;
  onInsertVertex?: (panelIndex: number, edgeIndex: number, x: number, y: number) => void;
  scale?: number;
}

function computeCentroid(corners: number[][]): { x: number; y: number } {
  if (corners.length === 0) return { x: 0, y: 0 };
  let sumX = 0;
  let sumY = 0;
  for (const corner of corners) {
    sumX += corner[0];
    sumY += corner[1];
  }
  return { x: sumX / corners.length, y: sumY / corners.length };
}

export function PolygonLayer({
  panels,
  selectedPanelIndex,
  mode,
  onSelectPanel,
  onMoveVertex,
  onInsertVertex,
  scale = 1,
}: PolygonLayerProps) {
  const inv = 1 / scale;
  const vertexR = 5 * inv;
  const editVertexR = 7 * inv;
  const midpointR = 5 * inv;
  const strokeW = 1.5 * inv;
  const selectedStrokeW = 2.5 * inv;
  const fontSize = 11 * inv;
  const labelOffset = 7 * inv;

  const isEditMode = mode === "edit";

  return (
    <>
      {panels.map((panel, index) => {
        const color = PANEL_PALETTE[index % 16];
        const isSelected = selectedPanelIndex === index;
        const points = panel.corners_pix.flat();
        const centroid = computeCentroid(panel.corners_pix);
        const isEditable = isEditMode && isSelected;

        return (
          <Group key={panel.id}>
            {/* Polygon fill + stroke */}
            <Line
              points={points}
              closed={true}
              fill={`${color}40`}
              stroke={isSelected ? "#3b82f6" : `${color}cc`}
              strokeWidth={isSelected ? selectedStrokeW : strokeW}
              listening={mode === "select" || isEditMode}
              onClick={() => {
                if (mode === "select" || isEditMode) {
                  onSelectPanel(index);
                }
              }}
            />

            {/* Panel ID label */}
            <Text
              x={centroid.x - labelOffset}
              y={centroid.y - labelOffset}
              text={String(panel.id)}
              fontSize={fontSize}
              fill="#ffffff"
              fontStyle="bold"
              listening={false}
            />

            {/* Corner vertices */}
            {panel.corners_pix.map((corner, ci) => (
              <Circle
                key={`v-${ci}`}
                x={corner[0]}
                y={corner[1]}
                radius={isEditable ? editVertexR : vertexR}
                fill={isEditable ? "#3b82f6" : "#ffffff"}
                stroke={isEditable ? "#ffffff" : color}
                strokeWidth={strokeW}
                draggable={isEditMode}
                listening={isEditMode}
                onDragMove={(e: KonvaEventObject<DragEvent>) => {
                  // Live update during drag for real-time shared vertex feedback
                  if (isEditMode && onMoveVertex) {
                    onMoveVertex(index, ci, e.target.x(), e.target.y());
                  }
                }}
                onDragEnd={(e: KonvaEventObject<DragEvent>) => {
                  if (isEditMode && onMoveVertex) {
                    onMoveVertex(index, ci, e.target.x(), e.target.y());
                  }
                }}
              />
            ))}

            {/* Edge midpoint connectors — in edit mode for selected panel */}
            {isEditable &&
              panel.corners_pix.map((corner, ci) => {
                const next = panel.corners_pix[(ci + 1) % panel.corners_pix.length];
                const mx = (corner[0] + next[0]) / 2;
                const my = (corner[1] + next[1]) / 2;
                return (
                  <Group key={`m-${ci}`}>
                    {/* Invisible larger hit area */}
                    <Circle
                      x={mx}
                      y={my}
                      radius={midpointR * 2}
                      fill="transparent"
                      listening={true}
                      onClick={() => {
                        if (onInsertVertex) {
                          onInsertVertex(index, ci, mx, my);
                        }
                      }}
                    />
                    {/* Visible small dot */}
                    <Circle
                      x={mx}
                      y={my}
                      radius={midpointR * 0.6}
                      fill="#3b82f680"
                      stroke="#3b82f6"
                      strokeWidth={strokeW * 0.5}
                      listening={false}
                    />
                  </Group>
                );
              })}
          </Group>
        );
      })}
    </>
  );
}
