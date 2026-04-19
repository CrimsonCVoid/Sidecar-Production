"use client";

import { Circle } from "react-konva";

interface AutoCloseIndicatorProps {
  x: number;
  y: number;
  visible: boolean;
}

export function AutoCloseIndicator({ x, y, visible }: AutoCloseIndicatorProps) {
  if (!visible) return null;
  return (
    <Circle
      x={x}
      y={y}
      radius={4}
      stroke="#22c55e"
      strokeWidth={1}
      fill="rgba(34, 197, 94, 0.3)"
      listening={false}
    />
  );
}
