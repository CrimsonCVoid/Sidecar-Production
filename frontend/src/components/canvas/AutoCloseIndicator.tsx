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
      radius={10}
      stroke="#22c55e"
      strokeWidth={2}
      fill="transparent"
      listening={false}
    />
  );
}
