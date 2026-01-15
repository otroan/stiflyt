/**
 * Utilities for saving and loading changesets to/from local files
 */
import type { Changeset, LocalEvent, ChangeEvent } from '../types';

export interface ChangesetFileData {
  changeset: Changeset | null;
  events: (LocalEvent | ChangeEvent)[];
  routeNumber?: string;
  exportedAt: string;
  version: string;
}

const FILE_VERSION = '1.0.0';

/**
 * Save changeset and events to a JSON file
 */
export function saveChangesetToFile(
  changeset: Changeset | null,
  events: LocalEvent[],
  routeNumber?: string | null
): void {
  const data: ChangesetFileData = {
    changeset,
    events,
    routeNumber: routeNumber || undefined,
    exportedAt: new Date().toISOString(),
    version: FILE_VERSION,
  };

  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  
  // Generate filename
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
  const filename = changeset
    ? `changeset-${changeset.id}-${timestamp}.json`
    : `changeset-local-${routeNumber || 'unsaved'}-${timestamp}.json`;
  
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Load changeset and events from a JSON file
 */
export async function loadChangesetFromFile(
  file: File
): Promise<ChangesetFileData> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string;
        const data = JSON.parse(text) as ChangesetFileData;
        
        // Validate file format
        if (!data.version) {
          throw new Error('Ugyldig filformat: mangler versjon');
        }
        if (data.version !== FILE_VERSION) {
          console.warn(`Filversjon ${data.version} er forskjellig fra forventet ${FILE_VERSION}`);
        }
        if (!data.events || !Array.isArray(data.events)) {
          throw new Error('Ugyldig filformat: mangler events array');
        }
        
        resolve(data);
      } catch (error) {
        reject(new Error(`Kunne ikke lese fil: ${error instanceof Error ? error.message : 'Ukjent feil'}`));
      }
    };
    
    reader.onerror = () => {
      reject(new Error('Kunne ikke lese fil'));
    };
    
    reader.readAsText(file);
  });
}

/**
 * Save to localStorage as backup (optional)
 */
export function saveToLocalStorage(
  changeset: Changeset | null,
  events: LocalEvent[],
  routeNumber?: string | null
): void {
  try {
    const data: ChangesetFileData = {
      changeset,
      events,
      routeNumber: routeNumber || undefined,
      exportedAt: new Date().toISOString(),
      version: FILE_VERSION,
    };
    
    const key = changeset
      ? `changeset-${changeset.id}`
      : `changeset-local-${routeNumber || 'unsaved'}`;
    
    localStorage.setItem(key, JSON.stringify(data));
  } catch (error) {
    console.warn('Kunne ikke lagre til localStorage:', error);
  }
}

/**
 * Load from localStorage (optional)
 */
export function loadFromLocalStorage(
  key: string
): ChangesetFileData | null {
  try {
    const data = localStorage.getItem(key);
    if (!data) return null;
    
    return JSON.parse(data) as ChangesetFileData;
  } catch (error) {
    console.warn('Kunne ikke laste fra localStorage:', error);
    return null;
  }
}
