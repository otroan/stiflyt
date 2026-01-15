/**
 * Tests for geometry utility functions
 */
import { describe, it, expect } from 'vitest';
import { findClosestPointOnLine, splitLineStringAtPoint, isNewSegment } from '../geometry';
import type { GeoJSON } from 'geojson';

describe('geometry utilities', () => {
  describe('findClosestPointOnLine', () => {
    it('should return the clicked point if line is empty', () => {
      const clickedPoint = [10, 20];
      const lineCoordinates: number[][] = [];
      const result = findClosestPointOnLine(clickedPoint, lineCoordinates);
      expect(result).toEqual(clickedPoint);
    });

    it('should return the single point if line has one coordinate', () => {
      const clickedPoint = [10, 20];
      const lineCoordinates = [[5, 5]];
      const result = findClosestPointOnLine(clickedPoint, lineCoordinates);
      expect(result).toEqual([5, 5]);
    });

    it('should find closest point on a simple line segment', () => {
      const clickedPoint = [5, 5];
      const lineCoordinates = [
        [0, 0],
        [10, 0],
      ];
      const result = findClosestPointOnLine(clickedPoint, lineCoordinates);
      expect(result[0]).toBeCloseTo(5, 5);
      expect(result[1]).toBeCloseTo(0, 5);
    });

    it('should find closest point on a multi-segment line', () => {
      const clickedPoint = [5, 5];
      const lineCoordinates = [
        [0, 0],
        [10, 0],
        [10, 10],
      ];
      const result = findClosestPointOnLine(clickedPoint, lineCoordinates);
      // Should be on the first segment (closer)
      expect(result[0]).toBeCloseTo(5, 5);
      expect(result[1]).toBeCloseTo(0, 5);
    });
  });

  describe('splitLineStringAtPoint', () => {
    it('should split a simple line at a point', () => {
      const lineString: GeoJSON.LineString = {
        type: 'LineString',
        coordinates: [
          [0, 0],
          [10, 0],
        ],
      };
      const splitPoint = [5, 0];
      const [first, second] = splitLineStringAtPoint(lineString, splitPoint);

      expect(first.type).toBe('LineString');
      expect(second.type).toBe('LineString');
      expect(first.coordinates).toHaveLength(2);
      expect(second.coordinates).toHaveLength(2);
      expect(first.coordinates[0]).toEqual([0, 0]);
      expect(first.coordinates[1]).toEqual([5, 0]);
      expect(second.coordinates[0]).toEqual([5, 0]);
      expect(second.coordinates[1]).toEqual([10, 0]);
    });

    it('should split at an existing vertex', () => {
      const lineString: GeoJSON.LineString = {
        type: 'LineString',
        coordinates: [
          [0, 0],
          [5, 0],
          [10, 0],
        ],
      };
      const splitPoint = [5, 0];
      const [first, second] = splitLineStringAtPoint(lineString, splitPoint);

      expect(first.coordinates).toHaveLength(2);
      expect(second.coordinates).toHaveLength(2);
      expect(first.coordinates[1]).toEqual([5, 0]);
      expect(second.coordinates[0]).toEqual([5, 0]);
    });

    it('should throw error for line with less than 2 coordinates', () => {
      const lineString: GeoJSON.LineString = {
        type: 'LineString',
        coordinates: [[0, 0]],
      };
      const splitPoint = [5, 0];

      expect(() => splitLineStringAtPoint(lineString, splitPoint)).toThrow(
        'LineString must have at least 2 coordinates'
      );
    });
  });

  describe('isNewSegment', () => {
    it('should return true for temp_id starting with tmp_', () => {
      expect(isNewSegment('tmp_12345')).toBe(true);
      expect(isNewSegment('tmp_abc-def')).toBe(true);
    });

    it('should return false for regular segment IDs', () => {
      expect(isNewSegment('12345')).toBe(false);
      expect(isNewSegment('segment_123')).toBe(false);
      expect(isNewSegment('')).toBe(false);
    });
  });
});
