"""Interactive panel labeler: click corners on a DSM hillshade, save mask.npy.

Usage:
    python -m roof_pipeline.label_panels path/to/dsm.tif [--out mask.npy]

Controls (focus the matplotlib window first):
    Left click   add a corner to the current panel
    Scroll       zoom in/out under the cursor
    Right drag   pan (matplotlib toolbar's hand tool also works)
    ENTER        finish the current panel, start the next one
    BACKSPACE    undo the last corner of the current panel
    F            re-fit view to the building footprint
    S            save mask.npy + sidecar JSON, exit
    Q            quit without saving
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LightSource
from scipy.ndimage import binary_closing, binary_opening, label
from skimage.draw import polygon as draw_polygon

log = logging.getLogger(__name__)


def _shaded_relief(dsm: np.ndarray, res_m: float) -> np.ndarray:
    """Composite hillshade + terrain colormap -- gives a 'real roof' look.

    Returns an (H, W, 4) RGBA image. Elevation drives the color (blue/green
    low, brown/white high) while a 315/45 sun angle adds 3D shading so the
    roof faces visually pop out from the surrounding ground.
    """
    import matplotlib.cm as cm
    filled = np.where(np.isnan(dsm), np.nanmin(dsm), dsm)
    ls = LightSource(azdeg=315, altdeg=45)
    rgba = ls.shade(
        filled, cmap=cm.terrain, blend_mode="soft",
        vert_exag=2.5, dx=res_m, dy=res_m,
        vmin=float(np.nanpercentile(dsm, 2)),
        vmax=float(np.nanpercentile(dsm, 98)),
    )
    return rgba


# Distinct, high-saturation colors so adjacent panels never blend together.
_PANEL_COLORS = [
    "#e6194B", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#9A6324", "#800000",
    "#aaffc3", "#808000", "#000075", "#fabed4", "#469990",
]


def _building_bbox(dsm: np.ndarray, pad_px: int = 15) -> tuple[float, float, float, float]:
    """Estimate the building's pixel bbox so we can auto-zoom the view.

    Heuristic: in a typical Google Solar tile the surrounding ground/trees
    can also be elevated, so a simple threshold catches the whole image.
    Instead, threshold above (median + 1.5 m), morphologically close gaps,
    label connected components, and pick the largest one as the building.
    Returns (col_min, col_max, row_min, row_max) clamped to the image.
    """
    h, w = dsm.shape
    valid = dsm[~np.isnan(dsm)]
    if valid.size == 0:
        return (0.0, w - 1.0, 0.0, h - 1.0)
    ground = float(np.median(valid))
    above = (dsm - ground) > 1.5
    # Open first to break thin tree-canopy connections, then close to fill
    # the small notches inside the actual roof shape.
    above = binary_opening(above, iterations=3)
    above = binary_closing(above, iterations=3)
    if above.sum() < 50:
        return (0.0, w - 1.0, 0.0, h - 1.0)

    labels, n = label(above)
    if n == 0:
        return (0.0, w - 1.0, 0.0, h - 1.0)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0  # background

    # Pick the FLATTEST big-enough component. Buildings have low elevation
    # std relative to their height-above-ground (planar roofs); tree
    # clusters have high std (lumpy canopy). This is the most reliable
    # discriminator on real Solar API tiles where trees often dominate
    # area-wise.
    min_pixels = 3000  # ~30 m^2 at 0.1 m/px
    best_id, best_score = 0, -1.0
    for cid in range(1, n + 1):
        if sizes[cid] < min_pixels:
            continue
        elev = dsm[labels == cid]
        std = float(np.std(elev))
        rise = float(np.mean(elev) - ground)
        if rise <= 0.5:
            continue
        # Lower std/rise ratio is more building-like; tiebreak on size.
        flatness = rise / max(std, 0.1)
        score = flatness * np.log(sizes[cid])
        if score > best_score:
            best_score = score
            best_id = cid
    if best_id == 0:
        best_id = int(np.argmax(sizes))

    rows, cols = np.where(labels == best_id)
    r0 = max(0, int(rows.min()) - pad_px)
    r1 = min(h - 1, int(rows.max()) + pad_px)
    c0 = max(0, int(cols.min()) - pad_px)
    c1 = min(w - 1, int(cols.max()) + pad_px)
    return (float(c0), float(c1), float(r0), float(r1))


class PanelLabeler:
    def __init__(self, dsm: np.ndarray, res_m: float, out_path: Path):
        self.dsm = dsm
        self.res_m = res_m
        self.out_path = out_path
        self.h, self.w = dsm.shape

        self.panels: list[list[tuple[float, float]]] = []   # finalized panels
        self.current: list[tuple[float, float]] = []        # in-progress panel

        self.fig, self.ax = plt.subplots(figsize=(13, 11))
        self.ax.imshow(_shaded_relief(dsm, res_m), origin="upper",
                       interpolation="bilinear")
        self.ax.set_title(self._title())

        # Auto-zoom to the building footprint so the user isn't squinting at a
        # 100x100 m tile to click corners on a 15 m roof.
        self._home_xlim, self._home_ylim = self._compute_home_view()
        self.ax.set_xlim(self._home_xlim)
        self.ax.set_ylim(self._home_ylim)  # already in axes order (y-down image)

        # Live overlays: in-progress polyline + done polygons
        self._cur_color = _PANEL_COLORS[0]
        self._cur_line, = self.ax.plot(
            [], [], color=self._cur_color, marker="o",
            linewidth=2.5, markersize=14, markeredgecolor="white",
            markeredgewidth=1.5,
        )
        self._done_artists: list = []

        # Pan-by-right-drag state
        self._pan_start: tuple[float, float] | None = None
        self._pan_xlim0: tuple[float, float] | None = None
        self._pan_ylim0: tuple[float, float] | None = None

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("button_release_event", self._on_release)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.fig.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self._saved = False

    def _compute_home_view(self) -> tuple[tuple[float, float], tuple[float, float]]:
        c0, c1, r0, r1 = _building_bbox(self.dsm)
        # imshow with origin='upper' puts y axis inverted; matplotlib expects
        # ylim in (bottom, top) which for an inverted axis means (high, low).
        return (c0, c1), (r1, r0)

    def _title(self) -> str:
        return (
            f"Panel #{len(self.panels) + 1}  ({len(self.current)} corners)\n"
            "L-click=add  ENTER=finish panel  BACKSPACE=undo  "
            "scroll=zoom  R-drag=pan  F=fit-building  H=fit-all  S=save  Q=quit"
        )

    def _refresh(self):
        if self.current:
            xs = [p[0] for p in self.current]
            ys = [p[1] for p in self.current]
            self._cur_line.set_data(xs, ys)
        else:
            self._cur_line.set_data([], [])
        self.ax.set_title(self._title())
        self.fig.canvas.draw_idle()

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        if event.button == 1:
            self.current.append((event.xdata, event.ydata))
            self._refresh()
        elif event.button == 3:
            # Right-button drag = pan
            self._pan_start = (event.x, event.y)
            self._pan_xlim0 = self.ax.get_xlim()
            self._pan_ylim0 = self.ax.get_ylim()

    def _on_release(self, event):
        if event.button == 3:
            self._pan_start = None

    def _on_motion(self, event):
        if self._pan_start is None or event.x is None or event.y is None:
            return
        # Convert pixel deltas to data-coord deltas via the axes transform
        inv = self.ax.transData.inverted()
        x0_data, y0_data = inv.transform(self._pan_start)
        x1_data, y1_data = inv.transform((event.x, event.y))
        dx = x0_data - x1_data
        dy = y0_data - y1_data
        x0, x1 = self._pan_xlim0
        y0, y1 = self._pan_ylim0
        self.ax.set_xlim(x0 + dx, x1 + dx)
        self.ax.set_ylim(y0 + dy, y1 + dy)
        self.fig.canvas.draw_idle()

    def _on_scroll(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        # Punchy zoom: scroll up = 2x in, scroll down = 2x out
        scale = 0.5 if event.button == "up" else 2.0
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        cx, cy = event.xdata, event.ydata
        self.ax.set_xlim(cx + (x0 - cx) * scale, cx + (x1 - cx) * scale)
        self.ax.set_ylim(cy + (y0 - cy) * scale, cy + (y1 - cy) * scale)
        self.fig.canvas.draw_idle()

    def _finalize_current(self):
        if len(self.current) < 3:
            log.warning("need >= 3 corners to finish a panel; got %d", len(self.current))
            return
        self.panels.append(self.current)
        pid = len(self.panels)
        color = _PANEL_COLORS[(pid - 1) % len(_PANEL_COLORS)]
        # Draw the finalized polygon as a colored patch
        xs = [p[0] for p in self.current] + [self.current[0][0]]
        ys = [p[1] for p in self.current] + [self.current[0][1]]
        artist, = self.ax.fill(xs, ys, facecolor=color, alpha=0.35,
                               edgecolor=color, linewidth=2.0)
        self._done_artists.append(artist)
        # Label the panel with its ID at the centroid
        cx = float(np.mean([p[0] for p in self.current]))
        cy = float(np.mean([p[1] for p in self.current]))
        txt = self.ax.text(
            cx, cy, str(pid),
            color="white", fontsize=15, fontweight="bold",
            ha="center", va="center",
            bbox=dict(boxstyle="circle,pad=0.35", fc=color, ec="white",
                      alpha=0.9, linewidth=1.5),
        )
        self._done_artists.append(txt)
        self.current = []
        # Advance the in-progress color to the next panel's color
        self._cur_color = _PANEL_COLORS[pid % len(_PANEL_COLORS)]
        self._cur_line.set_color(self._cur_color)
        self._cur_line.set_markerfacecolor(self._cur_color)
        self._refresh()

    def _on_key(self, event):
        key = (event.key or "").lower()
        if key == "enter":
            self._finalize_current()
        elif key == "backspace":
            if self.current:
                self.current.pop()
                self._refresh()
        elif key == "f":
            self.ax.set_xlim(self._home_xlim)
            self.ax.set_ylim(self._home_ylim)
            self.fig.canvas.draw_idle()
        elif key == "h":
            self.ax.set_xlim(0, self.w - 1)
            self.ax.set_ylim(self.h - 1, 0)
            self.fig.canvas.draw_idle()
        elif key == "s":
            self.save_and_close()
        elif key == "q":
            log.info("quit without saving")
            plt.close(self.fig)

    def save_and_close(self):
        if self.current:
            log.info("auto-finalizing in-progress panel before save")
            self._finalize_current()
        if not self.panels:
            log.warning("no panels labeled, nothing to save")
            plt.close(self.fig)
            return

        mask = np.zeros((self.h, self.w), dtype=np.uint8)
        valid = ~np.isnan(self.dsm)
        for pid, poly in enumerate(self.panels, start=1):
            cols = np.array([p[0] for p in poly])
            rows = np.array([p[1] for p in poly])
            rr, cc = draw_polygon(rows, cols, shape=(self.h, self.w))
            # Only keep pixels where the DSM has data
            keep = valid[rr, cc]
            mask[rr[keep], cc[keep]] = pid

        np.save(self.out_path, mask)
        sidecar = self.out_path.with_suffix(".json")
        with open(sidecar, "w") as f:
            json.dump({
                "res_m": self.res_m,
                "shape": list(mask.shape),
                "panel_count": int(mask.max()),
                "panel_pixel_counts": {
                    str(i): int((mask == i).sum()) for i in range(1, mask.max() + 1)
                },
                # Original click coords (col_px, row_px) per panel. The mask
                # is for plane fitting; THESE are the authoritative polygon
                # vertices for mesh + cut sheets so we get exactly N corners
                # and perfectly straight edges instead of stairstepped contours.
                "panels": [
                    {"id": i + 1, "corners_pix": [[float(x), float(y)] for x, y in poly]}
                    for i, poly in enumerate(self.panels)
                ],
            }, f, indent=2)

        log.info("saved %s and %s (%d panels)", self.out_path, sidecar, mask.max())
        self._saved = True
        plt.close(self.fig)

    def run(self) -> bool:
        plt.show()
        return self._saved


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("dsm", type=Path, help="GeoTIFF DSM path")
    ap.add_argument("--out", type=Path, default=None, help="output mask .npy path")
    args = ap.parse_args()

    out_path = args.out or args.dsm.with_suffix(".mask.npy")

    with rasterio.open(args.dsm) as src:
        dsm = src.read(1).astype(np.float32)
        # rasterio returns the affine; |a| is x-resolution in CRS units (meters for UTM)
        res_m = abs(float(src.transform.a))
        nodata = src.nodata
    if nodata is not None:
        dsm = np.where(dsm == nodata, np.nan, dsm)

    log.info("loaded DSM: shape=%s, res=%.3f m/px, nan_pct=%.1f%%",
             dsm.shape, res_m, 100.0 * np.isnan(dsm).mean())

    labeler = PanelLabeler(dsm, res_m, out_path)
    saved = labeler.run()
    if not saved:
        log.warning("exited without saving")


if __name__ == "__main__":
    main()
