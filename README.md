# roof_pipeline

Local Python prototype that turns a **pre-segmented** roof DSM into a 3D mesh
and a multi-page PDF of dimensioned panel cut sheets. Built to validate the
approach on a Mac before porting to a DigitalOcean API backend that the
Next.js frontend (My Metal Roofer) will call.

## Inputs

- DSM (digital surface model): 2D float array of elevations in meters.
- Panel mask: 2D integer array same shape as the DSM. `0 = background`,
  `1..N = individual panel regions`. Produced by a separate human-in-the-loop
  labeling tool — the pipeline does **not** segment.
- Pixel resolution: meters per pixel.

For local testing the pipeline uses `synthetic.py` to generate a simple
2-panel gable. Swapping in real data later means replacing the synthetic
call in `main.py` with a `rasterio.open(path).read(1)` for the DSM and a
`np.load(path)` for the mask.

## Pipeline

1. **Plane fitting** (`planes.py`) — SVD per panel, normal oriented sky-up,
   stores RMS orthogonal residual.
2. **Boundary extraction** (`boundaries.py`) — OpenCV contour, RDP simplify,
   bilinear z-lift, project onto fitted plane so polygon is perfectly planar.
3. **Edge snapping** (`snapping.py`) — pairwise edge match within tolerance,
   replace with midline so ridges close cleanly.
4. **Mesh build** (`mesh.py`) — earcut triangulation in each plane's local
   2D frame, concatenate, export OBJ + glTF via trimesh.
5. **Cut-sheet PDF** (`cutsheets.py`) — un-rotate each panel to horizontal,
   render dimensioned drawing (ft-in edges, interior angles), embed 3D
   context inset with the active panel highlighted.

## Setup and run

```bash
cd /Users/carterbrady/roof_pipeline
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m roof_pipeline.main
```

Outputs land in `output/`:

```
output/roof.obj
output/roof.gltf
output/cutsheets.pdf
```

## Swapping in real data

```python
import numpy as np, rasterio
from roof_pipeline.planes import fit_all_panels
from roof_pipeline.boundaries import extract_panel_polygons
from roof_pipeline.snapping import snap_shared_edges
from roof_pipeline.mesh import build_roof_mesh, export_mesh
from roof_pipeline.cutsheets import write_cutsheets_pdf

with rasterio.open("dsm.tif") as src:
    dsm = src.read(1).astype("float32")
    res_m = src.res[0]
mask = np.load("panel_mask.npy").astype("uint8")

planes = fit_all_panels(dsm, mask, res_m)
polys = extract_panel_polygons(mask, dsm, res_m, planes)
polys = snap_shared_edges(polys, tol=0.15)
mesh = build_roof_mesh(polys, planes)
export_mesh(mesh, "output")
write_cutsheets_pdf(polys, planes, mesh, "output/cutsheets.pdf")
```
