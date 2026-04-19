"use client";

import { Circle, Line } from "react-konva";

interface DrawingLayerProps {
  activeDrawing: number[][] | null;
  cursorPosition: { x: number; y: number } | null;
}

export function DrawingLayer({ activeDrawing, cursorPosition }: DrawingLayerProps) {
  if (!activeDrawing || activeDrawing.length === 0) return null;

  const points = activeDrawing.flat();

  // Ghost line from last vertex to cursor
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
        strokeWidth={1}
        closed={false}
        dash={[8, 4]}
        listening={false}
      />
      {ghostPoints && (
        <Line
          points={ghostPoints}
          stroke="#3b82f6"
          strokeWidth={1}
          opacity={0.5}
          listening={false}
        />
      )}
      {activeDrawing.map((vertex, i) => (
        <Circle
          key={i}
          x={vertex[0]}
          y={vertex[1]}
          radius={3}
          fill="#ffffff"
          listening={false}
        />
      ))}
    </>
  );
}
