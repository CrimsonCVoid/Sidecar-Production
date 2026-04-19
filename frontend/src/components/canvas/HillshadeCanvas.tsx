"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Stage, Layer, Image as KonvaImage } from "react-konva";
import useImage from "use-image";
import type { KonvaEventObject } from "konva/lib/Node";
import { useLabelerStore } from "@/stores/labeler-store";
import type { PanelData } from "@/stores/labeler-store";
import { PolygonLayer } from "./PolygonLayer";
import { DrawingLayer } from "./DrawingLayer";
import { MagnetIndicator } from "./MagnetIndicator";
import { AutoCloseIndicator } from "./AutoCloseIndicator";
import { SnapPreviewLayer } from "./SnapPreviewLayer";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const MAGNET_RADIUS_PX = 12;
const AUTOCLOSE_RADIUS_PX = 10;
const SCALE_BY = 1.05;
const MIN_SCALE = 0.1;
const MAX_SCALE = 10;

function findNearestVertex(
  point: { x: number; y: number },
  panels: PanelData[],
  excludePanelIndex?: number,
): { vertex: number[]; distance: number } | null {
  let nearest: { vertex: number[]; distance: number } | null = null;
  for (let i = 0; i < panels.length; i++) {
    if (i === excludePanelIndex) continue;
    for (const corner of panels[i].corners_pix) {
      const dx = point.x - corner[0];
      const dy = point.y - corner[1];
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < MAGNET_RADIUS_PX && (!nearest || dist < nearest.distance)) {
        nearest = { vertex: corner, distance: dist };
      }
    }
  }
  return nearest;
}

interface HillshadeCanvasProps {
  sampleId: string;
  showHeatmap: boolean;
  heatmapOpacity: number;
}

export function HillshadeCanvas({ sampleId, showHeatmap, heatmapOpacity }: HillshadeCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<{ x: () => number; y: () => number; scaleX: () => number; scaleY: () => number; scale: (s: { x: number; y: number }) => void; position: (p: { x: number; y: number }) => void; getPointerPosition: () => { x: number; y: number } | null } | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  const [cursorPosition, setCursorPosition] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [magnetTarget, setMagnetTarget] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [autoCloseTarget, setAutoCloseTarget] = useState<{
    x: number;
    y: number;
  } | null>(null);

  const panels = useLabelerStore((s) => s.panels);
  const activeDrawing = useLabelerStore((s) => s.activeDrawing);
  const mode = useLabelerStore((s) => s.mode);
  const selectedPanelIndex = useLabelerStore((s) => s.selectedPanelIndex);
  const addVertex = useLabelerStore((s) => s.addVertex);
  const closePolygon = useLabelerStore((s) => s.closePolygon);
  const selectPanel = useLabelerStore((s) => s.selectPanel);

  // Satellite RGB as base layer
  const rgbUrl = `${API_BASE}/api/hillshade/${sampleId}/rgb`;
  const [image, imageStatus] = useImage(rgbUrl, "anonymous");

  // DSM heatmap as toggleable overlay
  const heatmapUrl = `${API_BASE}/api/hillshade/${sampleId}/heatmap`;
  const [heatmapImage] = useImage(heatmapUrl, "anonymous");

  // Auto-fit image to canvas on first load
  const [hasFitImage, setHasFitImage] = useState(false);
  useEffect(() => {
    if (image && !hasFitImage && stageRef.current) {
      const stage = stageRef.current;
      const scaleX = dimensions.width / image.width;
      const scaleY = dimensions.height / image.height;
      const fitScale = Math.min(scaleX, scaleY) * 0.95;
      const offsetX = (dimensions.width - image.width * fitScale) / 2;
      const offsetY = (dimensions.height - image.height * fitScale) / 2;
      stage.scale({ x: fitScale, y: fitScale });
      stage.position({ x: offsetX, y: offsetY });
      setHasFitImage(true);
    }
  }, [image, hasFitImage, dimensions]);

  // ResizeObserver for responsive canvas
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  function getImageCoords(stage: {
    x: () => number;
    y: () => number;
    scaleX: () => number;
    scaleY: () => number;
    getPointerPosition: () => { x: number; y: number } | null;
  }): { x: number; y: number } | null {
    const pos = stage.getPointerPosition();
    if (!pos) return null;
    const imageX = (pos.x - stage.x()) / stage.scaleX();
    const imageY = (pos.y - stage.y()) / stage.scaleY();
    return { x: imageX, y: imageY };
  }

  function handleMouseMove(e: KonvaEventObject<MouseEvent>) {
    const stage = e.target.getStage();
    if (!stage) return;
    const coords = getImageCoords(stage);
    if (!coords) return;

    setCursorPosition(coords);

    // Update magnet indicator
    if (mode === "draw") {
      const snap = findNearestVertex(coords, panels);
      setMagnetTarget(snap ? { x: snap.vertex[0], y: snap.vertex[1] } : null);

      // Update auto-close indicator
      if (activeDrawing && activeDrawing.length >= 3) {
        const first = activeDrawing[0];
        const dx = coords.x - first[0];
        const dy = coords.y - first[1];
        if (Math.sqrt(dx * dx + dy * dy) < AUTOCLOSE_RADIUS_PX) {
          setAutoCloseTarget({ x: first[0], y: first[1] });
        } else {
          setAutoCloseTarget(null);
        }
      } else {
        setAutoCloseTarget(null);
      }
    } else {
      setMagnetTarget(null);
      setAutoCloseTarget(null);
    }
  }

  function handleStageClick(e: KonvaEventObject<MouseEvent>) {
    const stage = e.target.getStage();
    if (!stage) return;
    const coords = getImageCoords(stage);
    if (!coords) return;

    if (mode === "select") {
      if (e.target === stage) {
        selectPanel(null);
      }
      return;
    }

    // Draw mode
    const shiftHeld = e.evt.shiftKey;
    let placeX = coords.x;
    let placeY = coords.y;

    // Check auto-close first
    if (activeDrawing && activeDrawing.length >= 3) {
      const first = activeDrawing[0];
      const dx = coords.x - first[0];
      const dy = coords.y - first[1];
      if (Math.sqrt(dx * dx + dy * dy) < AUTOCLOSE_RADIUS_PX) {
        closePolygon();
        return;
      }
    }

    // Check magnet snap
    if (!shiftHeld) {
      const snap = findNearestVertex({ x: coords.x, y: coords.y }, panels);
      if (snap) {
        placeX = snap.vertex[0];
        placeY = snap.vertex[1];
      }
    }

    addVertex(placeX, placeY);
  }

  function handleWheel(e: KonvaEventObject<WheelEvent>) {
    e.evt.preventDefault();
    const stage = e.target.getStage();
    if (!stage) return;
    const oldScale = stage.scaleX();
    const pointer = stage.getPointerPosition();
    if (!pointer) return;
    const mousePointTo = {
      x: (pointer.x - stage.x()) / oldScale,
      y: (pointer.y - stage.y()) / oldScale,
    };
    const direction = e.evt.deltaY > 0 ? -1 : 1;
    const newScale = Math.min(
      MAX_SCALE,
      Math.max(
        MIN_SCALE,
        direction > 0 ? oldScale * SCALE_BY : oldScale / SCALE_BY,
      ),
    );
    stage.scale({ x: newScale, y: newScale });
    stage.position({
      x: pointer.x - mousePointTo.x * newScale,
      y: pointer.y - mousePointTo.y * newScale,
    });
  }

  return (
    <div ref={containerRef} className="w-full h-full">
      {imageStatus === "loading" && (
        <div className="flex items-center justify-center h-full text-zinc-500">
          Loading satellite image...
        </div>
      )}
      {imageStatus === "failed" && (
        <div className="flex items-center justify-center h-full text-red-400">
          Failed to load satellite image
        </div>
      )}
      <Stage
        ref={stageRef as React.RefObject<never>}
        width={dimensions.width}
        height={dimensions.height}
        draggable={true}
        onClick={handleStageClick}
        onMouseMove={handleMouseMove}
        onWheel={handleWheel}
      >
        <Layer>
          {image && <KonvaImage image={image} />}
          {showHeatmap && heatmapImage && (
            <KonvaImage image={heatmapImage} opacity={heatmapOpacity} />
          )}
          <PolygonLayer
            panels={panels}
            selectedPanelIndex={selectedPanelIndex}
            mode={mode}
            onSelectPanel={selectPanel}
          />
          <DrawingLayer
            activeDrawing={activeDrawing}
            cursorPosition={cursorPosition}
          />
          <MagnetIndicator
            x={magnetTarget?.x ?? 0}
            y={magnetTarget?.y ?? 0}
            visible={magnetTarget !== null}
          />
          <AutoCloseIndicator
            x={autoCloseTarget?.x ?? 0}
            y={autoCloseTarget?.y ?? 0}
            visible={autoCloseTarget !== null}
          />
          <SnapPreviewLayer />
        </Layer>
      </Stage>
    </div>
  );
}
