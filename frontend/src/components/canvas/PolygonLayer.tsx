"use client";

import { Circle, Group, Line, Text } from "react-konva";
import type { PanelData } from "@/stores/labeler-store";

const PANEL_PALETTE = [
  "#06b6d4", "#f97316", "#8b5cf6", "#84cc16",
  "#f43f5e", "#f59e0b", "#14b8a6", "#ec4899",
  "#0ea5e9", "#10b981", "#d946ef", "#6366f1",
  "#64748b", "#a8a29e", "#ef4444", "#3b82f6",
];

interface PolygonLayerProps {
  panels: PanelData[];
  selectedPanelIndex: number | null;
  mode: "draw" | "select";
  onSelectPanel: (index: number) => void;
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
}: PolygonLayerProps) {
  return (
    <>
      {panels.map((panel, index) => {
        const color = PANEL_PALETTE[index % 16];
        const isSelected = selectedPanelIndex === index;
        const points = panel.corners_pix.flat();
        const centroid = computeCentroid(panel.corners_pix);

        return (
          <Group key={panel.id}>
            <Line
              points={points}
              closed={true}
              fill={`${color}40`}
              stroke={isSelected ? "#3b82f6" : `${color}cc`}
              strokeWidth={isSelected ? 3 : 2}
              listening={mode === "select"}
              onClick={() => {
                if (mode === "select") {
                  onSelectPanel(index);
                }
              }}
            />
            <Text
              x={centroid.x - 8}
              y={centroid.y - 6}
              text={String(panel.id)}
              fontSize={12}
              fill="#ffffff"
              fontStyle="bold"
              listening={false}
            />
            {panel.corners_pix.map((corner, ci) => (
              <Circle
                key={ci}
                x={corner[0]}
                y={corner[1]}
                radius={4}
                fill="#ffffff"
                stroke={color}
                strokeWidth={1}
                listening={false}
              />
            ))}
          </Group>
        );
      })}
    </>
  );
}
