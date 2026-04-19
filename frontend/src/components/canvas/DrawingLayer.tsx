"use client";

import { Circle, Line } from "react-konva";

interface DrawingLayerProps {
  activeDrawing: number[][] | null;
  cursorPosition: { x: number; y: number } | null;
  scale?: number;
}

export function DrawingLayer({ activeDrawing, cursorPosition, scale = 1 }: DrawingLayerProps) {
  if (!activeDrawing || activeDrawing.length === 0) return null;

  const inv = 1 / scale;
  const points = activeDrawing.flat();

  const ghostPoints =
    cursorPosition && activeDrawing.length >= 1
      ? [
          activeDrawing[activeDrawing.length - 1][0],
          activeDrawing[activeDrawing.length - 1][1],
          cursorPosition.x,
          cursorPosition.y,
        ]
      : null;

  return (
    <>
      <Line
        points={points}
        stroke="#3b82f6"
        strokeWidth={1 * inv}
        closed={false}
        dash={[6 * inv, 3 * inv]}
        listening={false}
      />
      {ghostPoints && (
        <Line
          points={ghostPoints}
          stroke="#3b82f6"
          strokeWidth={1 * inv}
          opacity={0.5}
          listening={false}
        />
      )}
      {activeDrawing.map((vertex, i) => (
        <Circle
          key={i}
          x={vertex[0]}
          y={vertex[1]}
          radius={3 * inv}
          fill="#ffffff"
          listening={false}
        />
      ))}
    </>
  );
}
