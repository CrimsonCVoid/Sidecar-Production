"use client";

import { Circle, Group, Text } from "react-konva";
import { useLabelerStore } from "@/stores/labeler-store";

const VALENCE_COLORS: Record<number, { color: string; radius: number }> = {
  2: { color: "#22c55e", radius: 5 },
  3: { color: "#eab308", radius: 7 },
};
const DEFAULT_VALENCE = { color: "#ef4444", radius: 9 }; // 4+

function getValenceStyle(valence: number): { color: string; radius: number } {
  return VALENCE_COLORS[valence] || DEFAULT_VALENCE;
}

export function SnapPreviewLayer() {
  const snapPreview = useLabelerStore((s) => s.snapPreview);

  if (!snapPreview) return null;

  return (
    <>
      {snapPreview.features.map((feature) => {
        if (!feature.position_xyz) return null;
        const { color, radius } = getValenceStyle(feature.valence);
        // position_xyz is [x, y, z] in pixel coords (res_m=1.0 for preview)
        const x = feature.position_xyz[0];
        const y = feature.position_xyz[1];

        return (
          <Group key={feature.id}>
            <Circle
              x={x}
              y={y}
              radius={radius}
              fill={color}
              opacity={0.9}
              listening={true}
            />
            {/* Tooltip text rendered on hover -- simplified as static label */}
            <Text
              x={x + radius + 4}
              y={y - 6}
              text={`${feature.valence} panels meet here`}
              fontSize={12}
              fontStyle="600"
              fill="white"
              visible={false}
              name={`tooltip-${feature.id}`}
            />
          </Group>
        );
      })}
    </>
  );
}
