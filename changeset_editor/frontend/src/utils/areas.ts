/**
 * DNT area mappings (prefix -> full name)
 * Loaded from areas.yaml
 */
export interface Area {
  prefix: string;
  name: string;
}

let areasCache: Area[] | null = null;

/**
 * Load areas from areas.yaml file
 */
export async function loadAreas(): Promise<Area[]> {
  if (areasCache) {
    return areasCache;
  }

  try {
    const response = await fetch('/areas.yaml');
    if (!response.ok) {
      throw new Error(`Failed to load areas.yaml: ${response.statusText}`);
    }
    const text = await response.text();

    // Parse YAML-like format: "prefix: Name"
    const lines = text.split('\n').filter(line => line.trim() && !line.trim().startsWith('#'));
    const parsed: Area[] = [];

    for (const line of lines) {
      const match = line.match(/^(\w+):\s*(.+)$/);
      if (match) {
        parsed.push({
          prefix: match[1].trim(),
          name: match[2].trim(),
        });
      }
    }

    // Sort by name
    parsed.sort((a, b) => a.name.localeCompare(b.name, 'no'));

    areasCache = parsed;
    return parsed;
  } catch (error) {
    console.error('Error loading areas:', error);
    // Return empty array on error
    return [];
  }
}

/**
 * Get area by prefix
 */
export function getAreaByPrefix(prefix: string, areas: Area[]): Area | undefined {
  return areas.find(a => a.prefix === prefix);
}

/**
 * Get prefix by area name
 */
export function getPrefixByName(name: string, areas: Area[]): string | undefined {
  const area = areas.find(a => a.name === name);
  return area?.prefix;
}
