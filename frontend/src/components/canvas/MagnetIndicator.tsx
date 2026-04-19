"use client";

import { Circle } from "react-konva";

interface MagnetIndicatorProps {
  x: number;
  y: number;
  visible: boolean;
  scale?: number;
}

export function MagnetIndicator({ x, y, visible, scale = 1 }: MagnetIndicatorProps) {
  if (!visible) return null;
  const inv = 1 / scale;
  return (
    <Circle
      x={x}
      y={y}
      radius={4 * inv}
      stroke="#facc15"
      strokeWidth={1 * inv}
      fill="rgba(250, 204, 21, 0.3)"
      listening={false}
    />
  );
}
