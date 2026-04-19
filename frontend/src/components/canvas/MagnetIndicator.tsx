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
      radius={12}
      stroke="#facc15"
      strokeWidth={2}
      fill="transparent"
      listening={false}
    />
  );
}
