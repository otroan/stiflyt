/** Geometry utility functions for segment operations */
import type { GeoJSON } from 'geojson';

/**
 * Calculate distance between two points [lng, lat]
 */
function distance(p1: number[], p2: number[]): number {
  const dx = p2[0] - p1[0];
  const dy = p2[1] - p1[1];
  return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Calculate dot product of two 2D vectors
 */
function dotProduct(a: number[], b: number[]): number {
  return a[0] * b[0] + a[1] * b[1];
}

/**
 * Calculate distance from a point to a line segment
 * Returns the distance and the closest point on the segment
 */
function pointToLineDistance(
  point: number[],
  lineStart: number[],
  lineEnd: number[]
): { distance: number; point: number[]; t: number } {
  const A = point[0] - lineStart[0];
  const B = point[1] - lineStart[1];
  const C = lineEnd[0] - lineStart[0];
  const D = lineEnd[1] - lineStart[1];

  const dot = A * C + B * D;
  const lenSq = C * C + D * D;
  let param = -1;

  if (lenSq !== 0) param = dot / lenSq;

  let xx: number, yy: number;

  if (param < 0) {
    xx = lineStart[0];
    yy = lineStart[1];
    param = 0;
  } else if (param > 1) {
    xx = lineEnd[0];
    yy = lineEnd[1];
    param = 1;
  } else {
    xx = lineStart[0] + param * C;
    yy = lineStart[1] + param * D;
  }

  const dx = point[0] - xx;
  const dy = point[1] - yy;
  return {
    distance: Math.sqrt(dx * dx + dy * dy),
    point: [xx, yy],
    t: param,
  };
}

/**
 * Find the closest point on a LineString to a given point
 * Returns the closest point coordinates [lng, lat]
 */
export function findClosestPointOnLine(
  clickedPoint: number[],
  lineCoordinates: number[][]
): number[] {
  if (lineCoordinates.length === 0) {
    return clickedPoint;
  }
  if (lineCoordinates.length === 1) {
    return lineCoordinates[0];
  }

  let minDistance = Infinity;
  let closestPoint = lineCoordinates[0];
  let closestSegmentIndex = 0;
  let closestT = 0;

  for (let i = 0; i < lineCoordinates.length - 1; i++) {
    const p1 = lineCoordinates[i];
    const p2 = lineCoordinates[i + 1];

    const result = pointToLineDistance(clickedPoint, p1, p2);

    if (result.distance < minDistance) {
      minDistance = result.distance;
      closestPoint = result.point;
      closestSegmentIndex = i;
      closestT = result.t;
    }
  }

  return closestPoint;
}

/**
 * Split a LineString at a given point
 * Returns two LineString geometries
 */
export function splitLineStringAtPoint(
  lineString: GeoJSON.LineString,
  splitPoint: number[]
): [GeoJSON.LineString, GeoJSON.LineString] {
  const coords = lineString.coordinates;
  if (coords.length < 2) {
    throw new Error('LineString must have at least 2 coordinates');
  }

  // Find the segment to split
  let splitIndex = 0;
  let minDist = Infinity;
  let splitT = 0;

  for (let i = 0; i < coords.length - 1; i++) {
    const result = pointToLineDistance(splitPoint, coords[i], coords[i + 1]);
    if (result.distance < minDist) {
      minDist = result.distance;
      splitIndex = i;
      splitT = result.t;
    }
  }

  // Create two new geometries
  const firstPart = coords.slice(0, splitIndex + 1);
  // If split point is not at an existing vertex, add it
  if (splitT > 0 && splitT < 1) {
    firstPart.push(splitPoint);
  }
  // If splitT === 1, the split point is at coords[splitIndex + 1], which is already included

  const secondPart: number[][] = [];
  // If split point is not at an existing vertex, add it to the second part
  if (splitT > 0 && splitT < 1) {
    secondPart.push(splitPoint);
  }
  // Add remaining coordinates (starting from splitIndex + 1, or splitIndex + 2 if we added the point)
  secondPart.push(...coords.slice(splitIndex + 1));

  return [
    {
      type: 'LineString',
      coordinates: firstPart,
    },
    {
      type: 'LineString',
      coordinates: secondPart,
    },
  ];
}

/**
 * Check if a segment ID represents a new segment (temp_id) or existing segment (objid)
 */
export function isNewSegment(segmentId: string): boolean {
  // New segments have temp_id starting with "tmp_"
  return segmentId.startsWith('tmp_');
}
