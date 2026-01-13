/** Snap utilities for geometry editing */
import RBush from 'rbush';
import type { SnapTarget } from '../types';

interface SnapPoint {
  x: number;
  y: number;
  id: string;
  vertexIndex?: number;
}

export class SnapManager {
  private tree: RBush<SnapPoint>;
  private tolerance: number; // in pixels

  constructor(tolerance = 12) {
    this.tree = new RBush();
    this.tolerance = tolerance;
  }

  loadTargets(targets: SnapTarget[]): void {
    const points: SnapPoint[] = [];
    for (const target of targets) {
      for (let i = 0; i < target.vertices.length; i++) {
        const [lon, lat] = target.vertices[i];
        points.push({
          x: lon,
          y: lat,
          id: target.id,
          vertexIndex: i,
        });
      }
    }
    this.tree.load(points);
  }

  findNearest(
    lon: number,
    lat: number,
    map: L.Map
  ): { lon: number; lat: number; distance: number } | null {
    // Convert pixel tolerance to geographic distance
    const containerPoint = map.latLngToContainerPoint([lat, lon]);
    const tolerancePoint = map.containerPointToLatLng(
      L.point(containerPoint.x + this.tolerance, containerPoint.y)
    );
    const toleranceDegrees = Math.abs(tolerancePoint.lng - lon);

    const results = this.tree.search({
      minX: lon - toleranceDegrees,
      minY: lat - toleranceDegrees,
      maxX: lon + toleranceDegrees,
      maxY: lat + toleranceDegrees,
    });

    if (results.length === 0) {
      return null;
    }

    // Find closest point
    let nearest: SnapPoint | null = null;
    let minDistance = Infinity;

    for (const point of results) {
      const dx = point.x - lon;
      const dy = point.y - lat;
      const distance = Math.sqrt(dx * dx + dy * dy);

      if (distance < minDistance) {
        minDistance = distance;
        nearest = point;
      }
    }

    if (nearest && minDistance <= toleranceDegrees) {
      return {
        lon: nearest.x,
        lat: nearest.y,
        distance: minDistance,
      };
    }

    return null;
  }

  clear(): void {
    this.tree.clear();
  }
}
