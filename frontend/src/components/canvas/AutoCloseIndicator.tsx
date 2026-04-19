"use client";

import { Circle } from "react-konva";

interface AutoCloseIndicatorProps {
  x: number;
  y: number;
  visible: boolean;
  scale?: number;
}

export function AutoCloseIndicator({ x, y, visible, scale = 1 }: AutoCloseIndicatorProps) {
  if (!visible) return null;
  const inv = 1 / scale;
  return (
    <Circle
      x={x}
      y={y}
      radius={4 * inv}
      stroke="#22c55e"
      strokeWidth={1 * inv}
      fill="rgba(34, 197, 94, 0.3)"
      listening={false}
    />
  );
}
