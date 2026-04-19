"""Tests for three-pass expanding-tolerance vertex clustering."""

from __future__ import annotations

import numpy as np
import pytest

from roof_pipeline.planes import Plane
from roof_pipeline.panel_snap_v2.clustering import cluster_vertices


def _make_plane(normal=(0, 0, 1), centroid=(0, 0, 5)):
    """Helper: build a horizontal Plane."""
    n = np.array(normal, dtype=float)
    n /= np.linalg.norm(n)
    if n[2] < 0:
        n = -n
    c = np.array(centroid, dtype=float)
    return Plane(normal=n, centroid=c, rms_residual=0.01, d=float(n @ c))


class TestTransitiveCluster:
    """TEST-04: Multi-pass expansion clusters transitively."""

    def test_transitive_cluster_above_tol(self):
        """Three points at pairwise distances (0.9, 0.9, 1.3) with tol=1.0 cluster."""
        # Panel 1: single vertex at A=(0, 0, 5)
        # Panel 2: single vertex at B=(0.9, 0, 5)
        # Panel 3: single vertex at C
        # C needs dist(B,C)=0.9, dist(A,C)=1.3
        # C=(x,y,5): x^2+y^2=1.69, (x-0.9)^2+y^2=0.81
        # x^2+y^2=1.69, x^2-1.8x+0.81+y^2=0.81 => 1.69-1.8x=0 => x=1.69/1.8
        # y^2=1.69-x^2
        A = np.array([[0.0, 0.0, 5.0]])
        B = np.array([[0.9, 0.0, 5.0]])
        cx = 1.69 / 1.8  # ~0.9389
        cy = np.sqrt(1.69 - cx**2)  # ~0.8989
        C = np.array([[cx, cy, 5.0]])

        # Verify pairwise distances
        assert abs(np.linalg.norm(A - B) - 0.9) < 0.01
        assert abs(np.linalg.norm(B - C) - 0.9) < 0.01
        assert abs(np.linalg.norm(A - C) - 1.3) < 0.01

        plane = _make_plane()
        polygons = {1: A, 2: B, 3: C}
        planes = {1: plane, 2: plane, 3: plane}

        groups, items = cluster_vertices(polygons, planes, tol=1.0)

        # All three should be in one cluster
        cluster_sizes = [len(members) for members in groups.values()]
        assert max(cluster_sizes) == 3, f"Expected one cluster of size 3, got sizes {cluster_sizes}"

    def test_distant_points_stay_separate(self):
        """Two points at distance 2.0 with tol=1.0 remain separate."""
        A = np.array([[0.0, 0.0, 5.0]])
        B = np.array([[2.0, 0.0, 5.0]])

        plane = _make_plane()
        groups, items = cluster_vertices(
            {1: A, 2: B}, {1: plane, 2: plane}, tol=1.0,
        )

        # Each point in its own cluster
        cluster_sizes = sorted(len(m) for m in groups.values())
        assert cluster_sizes == [1, 1]


class TestMultiPassBenefit:
    """Verify multi-pass catches cases single-pass-at-full-tol misses."""

    def test_cumulative_passes(self):
        """Pass 1 at 0.3t merges A-B; pass 2 at 0.6t merges {A,B}-C."""
        # tol=1.0, so passes at 0.3, 0.6, 1.0
        # A=(0,0,5), B=(0.25,0,5) -- dist 0.25, within 0.3
        # C=(0.8,0,5) -- dist(B,C)=0.55, within 0.6 but not 0.3
        A = np.array([[0.0, 0.0, 5.0]])
        B = np.array([[0.25, 0.0, 5.0]])
        C = np.array([[0.8, 0.0, 5.0]])

        plane = _make_plane()
        groups, items = cluster_vertices(
            {1: A, 2: B, 3: C}, {1: plane, 2: plane, 3: plane}, tol=1.0,
        )

        cluster_sizes = [len(m) for m in groups.values()]
        assert max(cluster_sizes) == 3


class TestItemsStructure:
    """Verify items list structure."""

    def test_items_contain_pid_vi_xyz(self):
        """Items list has (pid, vertex_index, xyz) for every vertex."""
        poly1 = np.array([[0, 0, 5], [1, 0, 5], [0.5, 1, 5]], dtype=float)
        poly2 = np.array([[1, 0, 5], [2, 0, 5], [1.5, 1, 5]], dtype=float)

        plane = _make_plane()
        groups, items = cluster_vertices(
            {10: poly1, 20: poly2}, {10: plane, 20: plane}, tol=0.01,
        )

        # 3 vertices from poly1 + 3 from poly2 = 6 items
        assert len(items) == 6

        # Check structure: each item is (pid, vi, xyz)
        pids_seen = set()
        for pid, vi, xyz in items:
            pids_seen.add(pid)
            assert isinstance(vi, int)
            assert xyz.shape == (3,)

        assert pids_seen == {10, 20}
