/**
 * Tests for file storage utilities
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { saveChangesetToFile, loadChangesetFromFile, saveToLocalStorage, loadFromLocalStorage } from '../fileStorage';
import type { Changeset, LocalEvent } from '../../types';

// Mock DOM APIs
describe('fileStorage utilities', () => {
  beforeEach(() => {
    // Reset mocks
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('saveChangesetToFile', () => {
    it('should create a download link with changeset data', () => {
      const mockClick = vi.fn();
      const mockAppendChild = vi.fn();
      const mockRemoveChild = vi.fn();
      const mockCreateElement = vi.fn(() => ({
        href: '',
        download: '',
        click: mockClick,
      }));

      const mockCreateObjectURL = vi.fn(() => 'blob:url');
      const mockRevokeObjectURL = vi.fn();

      // Mock DOM methods
      global.URL.createObjectURL = mockCreateObjectURL;
      global.URL.revokeObjectURL = mockRevokeObjectURL;
      document.createElement = mockCreateElement as typeof document.createElement;
      document.body.appendChild = mockAppendChild;
      document.body.removeChild = mockRemoveChild;

      const changeset: Changeset = {
        id: 'test-123',
        title: 'Test Changeset',
        description: 'Test',
        status: 'draft',
        created_by: 'user',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        base_snapshot: 'default',
      };

      const events: LocalEvent[] = [];

      saveChangesetToFile(changeset, events, 'BRE001');

      expect(mockCreateElement).toHaveBeenCalledWith('a');
      expect(mockAppendChild).toHaveBeenCalled();
      expect(mockClick).toHaveBeenCalled();
      expect(mockRemoveChild).toHaveBeenCalled();
      expect(mockRevokeObjectURL).toHaveBeenCalledWith('blob:url');
    });

    it('should generate correct filename with changeset', () => {
      const mockClick = vi.fn();
      const mockCreateElement = vi.fn(() => ({
        href: '',
        download: '',
        click: mockClick,
      }));

      document.createElement = mockCreateElement as typeof document.createElement;
      document.body.appendChild = vi.fn();
      document.body.removeChild = vi.fn();
      global.URL.createObjectURL = vi.fn(() => 'blob:url');
      global.URL.revokeObjectURL = vi.fn();

      const changeset: Changeset = {
        id: 'test-123',
        title: 'Test',
        status: 'draft',
        created_by: 'user',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        base_snapshot: 'default',
      };

      saveChangesetToFile(changeset, [], 'BRE001');

      const createdElement = mockCreateElement.mock.results[0].value;
      expect(createdElement.download).toContain('changeset-test-123');
      expect(createdElement.download).toContain('.json');
    });
  });

  describe('loadChangesetFromFile', () => {
    it('should load valid changeset file', async () => {
      const fileData = {
        changeset: null,
        events: [],
        routeNumber: 'BRE001',
        exportedAt: '2024-01-01T00:00:00Z',
        version: '1.0.0',
      };

      const file = new File([JSON.stringify(fileData)], 'test.json', { type: 'application/json' });

      const result = await loadChangesetFromFile(file);

      expect(result).toEqual(fileData);
    });

    it('should reject file with missing version', async () => {
      const fileData = {
        changeset: null,
        events: [],
      };

      const file = new File([JSON.stringify(fileData)], 'test.json', { type: 'application/json' });

      await expect(loadChangesetFromFile(file)).rejects.toThrow('mangler versjon');
    });

    it('should reject file with missing events array', async () => {
      const fileData = {
        version: '1.0.0',
        changeset: null,
      };

      const file = new File([JSON.stringify(fileData)], 'test.json', { type: 'application/json' });

      await expect(loadChangesetFromFile(file)).rejects.toThrow('mangler events array');
    });

    it('should handle file read errors', async () => {
      const file = new File([''], 'test.json', { type: 'application/json' });
      // Mock FileReader to simulate error
      const originalFileReader = global.FileReader;
      global.FileReader = class {
        onerror: ((event: ProgressEvent<FileReader>) => void) | null = null;
        readAsText() {
          setTimeout(() => {
            if (this.onerror) {
              this.onerror(new ProgressEvent('error'));
            }
          }, 0);
        }
      } as any;

      await expect(loadChangesetFromFile(file)).rejects.toThrow('Kunne ikke lese fil');

      global.FileReader = originalFileReader;
    });
  });

  describe('localStorage utilities', () => {
    it('should save to localStorage', () => {
      const changeset: Changeset = {
        id: 'test-123',
        title: 'Test',
        status: 'draft',
        created_by: 'user',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        base_snapshot: 'default',
      };

      saveToLocalStorage(changeset, [], 'BRE001');

      const key = 'changeset-test-123';
      const data = localStorage.getItem(key);
      expect(data).toBeTruthy();
      if (data) {
        const parsed = JSON.parse(data);
        expect(parsed.changeset.id).toBe('test-123');
        expect(parsed.routeNumber).toBe('BRE001');
      }
    });

    it('should load from localStorage', () => {
      const changeset: Changeset = {
        id: 'test-123',
        title: 'Test',
        status: 'draft',
        created_by: 'user',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        base_snapshot: 'default',
      };

      saveToLocalStorage(changeset, [], 'BRE001');
      const result = loadFromLocalStorage('changeset-test-123');

      expect(result).toBeTruthy();
      expect(result?.changeset?.id).toBe('test-123');
    });

    it('should return null for non-existent key', () => {
      const result = loadFromLocalStorage('non-existent');
      expect(result).toBeNull();
    });
  });
});
