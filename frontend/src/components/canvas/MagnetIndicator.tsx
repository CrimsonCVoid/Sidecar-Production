"use client";

import { Circle } from "react-konva";

interface MagnetIndicatorProps {
  x: number;
  y: number;
  visible: boolean;
}

export function MagnetIndicator({ x, y, visible }: MagnetIndicatorProps) {
  if (!visible) return null;
  return (
    <Circle
      x={x}
      y={y}
      radius={4}
      stroke="#facc15"
      strokeWidth={1}
      fill="rgba(250, 204, 21, 0.3)"
      listening={false}
    />
  );
}
