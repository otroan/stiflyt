/**
 * Collapsible info panel component (replaces SidePanel)
 * Displays route info, changeset info, validation results, and events
 */
import { useState, useEffect } from 'react';
import type {
  Changeset,
  ChangeEvent,
  ValidationIssue,
  RouteValidationResponse,
  LocalEvent,
  SignsReportResponse,
  SignsMissingReport,
} from '../types';
import { isSegmentAddEvent, isSegmentUpdateGeomEvent } from '../types';
import { api, isAbortError } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';
import { SegmentEditForm } from './SegmentEditForm';
import { BulkSegmentEditForm } from './BulkSegmentEditForm';
import { RouteEditForm } from './RouteEditForm';
import type { SegmentUpdateAttrsEvent } from '../types';
import './InfoPanel.css';

interface InfoPanelProps {
  changeset: Changeset | null;
  routeNumber: string | null;
  selectedFeatureId?: string;
  selectedFeatureIds?: Set<string>; // Multi-select support
  selectedFeatureProperties?: Record<string, unknown> | null;
  selectedFeaturesMap?: Map<string, Record<string, unknown>>; // Map of all selected features
  localEvents?: LocalEvent[];
  localEventsCount?: number;
  onChangesetUpdate: () => void;
  onSaveChanges?: () => void;
  onLoadFromFile?: (file: File) => void;
  onPublish?: () => void;
  onFeatureUpdate?: (() => void) | ((event?: unknown) => void);
  loading?: boolean;
  shouldOpenEditForm?: boolean; // Flag to open edit form from MapView
  onEditFormOpened?: () => void; // Callback when edit form has been opened
  selectedSignDestinations?: Set<string>; // Selected sign destination keys
  onSignDestinationSelect?: (destKey: string, selected: boolean) => void; // Callback for destination selection
  onSignsPrefixChange?: (prefix: string) => void; // Callback when signs prefix changes
  activeMode?: 'inspection' | 'edit' | 'anchor-naming' | 'signs' | 'property-ownership';
  ownershipData?: any;
  selectedGeometryForOwnership?: GeoJSON.Geometry | null;
  onOwnershipDataChange?: (data: any) => void;
}

export function InfoPanel({
  changeset,
  routeNumber,
  selectedFeatureId,
  selectedFeatureIds = new Set(),
  selectedFeatureProperties,
  selectedFeaturesMap = new Map(),
  localEvents = [],
  localEventsCount = 0,
  onChangesetUpdate,
  onSaveChanges,
  onLoadFromFile,
  onPublish,
  onFeatureUpdate,
  loading = false,
  shouldOpenEditForm = false,
  onEditFormOpened,
  selectedSignDestinations = new Set(),
  onSignDestinationSelect,
  onSignsPrefixChange,
  activeMode = 'inspection',
  ownershipData,
  selectedGeometryForOwnership,
  onOwnershipDataChange,
}: InfoPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [events, setEvents] = useState<ChangeEvent[]>([]);
  const [validation, setValidation] = useState<{ errors: ValidationIssue[]; warnings: ValidationIssue[] } | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [showEditForm, setShowEditForm] = useState(false);
  const [showBulkEditForm, setShowBulkEditForm] = useState(false);
  const [showRouteEditForm, setShowRouteEditForm] = useState(false);
  
  // Debug logging for form visibility
  useEffect(() => {
    console.log('InfoPanel render state:', { 
      showEditForm, 
      selectedFeatureId, 
      selectedFeatureIdsSize: selectedFeatureIds.size,
      selectedFeatureIdsArray: Array.from(selectedFeatureIds),
      isOpen,
      shouldRenderSingleSelect: selectedFeatureId && selectedFeatureIds.size <= 1,
      shouldRenderForm: selectedFeatureId && selectedFeatureIds.size <= 1 && showEditForm
    });
  }, [showEditForm, selectedFeatureId, selectedFeatureIds, isOpen]);
  const [routeMetadata, setRouteMetadata] = useState<Record<string, unknown> | null>(null);
  const [routeValidation, setRouteValidation] = useState<RouteValidationResponse | null>(null);
  const [isLoadingRouteValidation, setIsLoadingRouteValidation] = useState(false);
  const [signsPrefix, setSignsPrefix] = useState('');
  const [signsReport, setSignsReport] = useState<SignsReportResponse | null>(null);
  const [signsMissing, setSignsMissing] = useState<SignsMissingReport | null>(null);
  const [isLoadingOwnership, setIsLoadingOwnership] = useState(false);

  // Load ownership data when geometry is selected in property-ownership mode
  useEffect(() => {
    if (activeMode === 'property-ownership' && selectedGeometryForOwnership && selectedGeometryForOwnership.type === 'LineString') {
      setIsLoadingOwnership(true);
      api.getGeometryOwners(selectedGeometryForOwnership)
        .then((data) => {
          if (onOwnershipDataChange) {
            onOwnershipDataChange(data);
          }
        })
        .catch((error) => {
          const appError = handleApiError(error, 'Property Ownership');
          notificationManager.error(`Kunne ikke laste grunneierinformasjon: ${appError.message}`);
        })
        .finally(() => {
          setIsLoadingOwnership(false);
        });
    }
  }, [activeMode, selectedGeometryForOwnership, onOwnershipDataChange]);
  const [isLoadingSigns, setIsLoadingSigns] = useState(false);
  const [isLoadingMissingSigns, setIsLoadingMissingSigns] = useState(false);
  const [signsError, setSignsError] = useState<string | null>(null);

  // Open edit form when requested from MapView
  useEffect(() => {
    if (shouldOpenEditForm) {
      console.log('Opening edit form:', { 
        selectedFeatureIdsSize: selectedFeatureIds.size, 
        selectedFeatureId, 
        routeNumber,
        hasChangeset: !!changeset,
        isOpen 
      });
      
      // Ensure panel is open when opening edit form
      setIsOpen(true);
      
      if (selectedFeatureIds.size > 1) {
        // Multiple segments selected - show bulk edit
        console.log('Opening bulk edit form');
        setShowBulkEditForm(true);
        setShowEditForm(false); // Ensure single edit is closed
      } else if (selectedFeatureId || selectedFeatureIds.size === 1) {
        // Single segment selected - show single edit
        console.log('Opening single edit form', { selectedFeatureId, selectedFeatureIdsSize: selectedFeatureIds.size });
        setShowEditForm(true);
        setShowBulkEditForm(false); // Ensure bulk edit is closed
      } else if (routeNumber) {
        // Route editing works with or without changeset
        console.log('Opening route edit form');
        setShowRouteEditForm(true);
        setShowEditForm(false); // Ensure single edit is closed
        setShowBulkEditForm(false); // Ensure bulk edit is closed
      } else {
        console.warn('No segment or route selected - cannot open edit form');
      }
      if (onEditFormOpened) {
        onEditFormOpened();
      }
    }
  }, [shouldOpenEditForm, selectedFeatureId, selectedFeatureIds, routeNumber, changeset, onEditFormOpened, isOpen]);

  // Auto-open panel when changeset is loaded, route is selected, or feature is selected
  useEffect(() => {
    if (changeset || routeNumber || selectedFeatureId) {
      setIsOpen(true);
    }
  }, [changeset?.id, routeNumber, selectedFeatureId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (changeset) {
      api.getEvents(changeset.id)
        .then((data) => setEvents(data.events))
        .catch((error) => {
          const appError = handleApiError(error, 'Load Events');
          notificationManager.error(`Kunne ikke laste events: ${appError.message}`);
        });
    } else {
      setEvents([]);
    }
  }, [changeset?.id]);

  // Load route metadata when route is selected (works with or without changeset)
  useEffect(() => {
    if (routeNumber) {
      const controller = new AbortController();
      api.getRoute(routeNumber, false, { signal: controller.signal })
        .then((data) => {
          setRouteMetadata({
            rutenummer: data.rutenummer,
            rutenavn: data.rutenavn,
            vedlikeholdsansvarlig: data.vedlikeholdsansvarlig,
            rutetype: data.rutetype,
            gradering: data.gradering,
          });
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          // Silently fail - route metadata is optional
          console.warn('Could not load route metadata:', error);
        });

      return () => {
        controller.abort();
      };
    }

    setRouteMetadata(null);
  }, [routeNumber]);

  // Load route validation when route is selected (works without changeset)
  useEffect(() => {
    if (routeNumber) {
      const controller = new AbortController();
      setIsLoadingRouteValidation(true);
      api.validateRoute(routeNumber, { signal: controller.signal })
        .then((data: RouteValidationResponse) => {
          setRouteValidation(data);
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          // Silently fail - route validation is optional
          console.warn('Could not load route validation:', error);
          setRouteValidation(null);
        })
        .finally(() => {
          setIsLoadingRouteValidation(false);
        });

      return () => {
        controller.abort();
      };
    }

    setRouteValidation(null);
  }, [routeNumber]);

  useEffect(() => {
    if (routeNumber && routeNumber.length >= 3) {
      setSignsPrefix((prev) => (prev ? prev : routeNumber.slice(0, 3)));
    }
  }, [routeNumber]);

  const handleValidate = async () => {
    if (!changeset) return;
    
    setIsValidating(true);
    try {
      const result = await api.validate(changeset.id);
      setValidation(result);
      if (result.errors.length === 0 && result.warnings.length === 0) {
        notificationManager.success('Validering fullført: Ingen feil funnet');
      } else {
        notificationManager.warning(
          `Validering fullført: ${result.errors.length} feil, ${result.warnings.length} advarsler`
        );
      }
    } catch (error) {
      const appError = handleApiError(error, 'Validation');
      notificationManager.error(`Validering feilet: ${appError.message}`);
    } finally {
      setIsValidating(false);
    }
  };

  const handleValidateRoute = async () => {
    if (!routeNumber) return;
    
    setIsLoadingRouteValidation(true);
    try {
      const result = await api.validateRoute(routeNumber);
      setRouteValidation(result);
      if (result.errors.length === 0 && result.warnings.length === 0) {
        notificationManager.success('Rutevalidering fullført: Ingen feil funnet');
      } else {
        notificationManager.warning(
          `Rutevalidering fullført: ${result.errors.length} feil, ${result.warnings.length} advarsler`
        );
      }
    } catch (error) {
      const appError = handleApiError(error, 'Route Validation');
      notificationManager.error(`Rutevalidering feilet: ${appError.message}`);
    } finally {
      setIsLoadingRouteValidation(false);
    }
  };

  const handlePublish = async () => {
    if (!changeset && !onPublish) return;
    
    if (!confirm('Send changeset to review? This will create a GitHub PR.')) {
      return;
    }

    // If we have onPublish prop (from App), use it (handles both cases: with/without changeset)
    if (onPublish) {
      setIsPublishing(true);
      try {
        await onPublish();
        onChangesetUpdate(); // Reload changeset after publish
      } catch (error) {
        // Error handling is done in App.tsx
      } finally {
        setIsPublishing(false);
      }
      return;
    }

    // Fallback: handle publish locally if no onPublish prop (shouldn't happen normally)
    if (!changeset) return;
    
    setIsPublishing(true);
    try {
      const result = await api.publish(changeset.id);
      notificationManager.success(
        `Changeset publisert! PR: ${result.pr_url || 'N/A'}`,
        0
      );
      onChangesetUpdate();
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Publish');
      
      // Try to extract validation errors from response
      if (error && typeof error === 'object' && 'response' in error) {
        try {
          const errorWithResponse = error as { response?: { json: () => Promise<unknown> } };
          const errorData = errorWithResponse.response 
            ? await errorWithResponse.response.json().catch(() => null)
            : null;
          
          if (errorData && typeof errorData === 'object' && errorData !== null) {
            const validationData = errorData as { errors?: ValidationIssue[]; warnings?: ValidationIssue[] };
            if (validationData.errors) {
              setValidation({ 
                errors: validationData.errors, 
                warnings: validationData.warnings || [] 
              });
              notificationManager.error(
                `Publisering feilet: ${validationData.errors.length} feil funnet. Se valideringspanel.`,
                0
              );
              return;
            }
          }
        } catch {
          // Ignore JSON parse errors
        }
      }
      
      notificationManager.error(`Publisering feilet: ${appError.message}`, 0);
    } finally {
      setIsPublishing(false);
    }
  };

  const escapeCsvValue = (value: unknown): string => {
    if (value === null || value === undefined) return '';
    const str = String(value);
    if (/[",\n]/.test(str)) {
      return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
  };

  const buildCsv = (rows: Record<string, unknown>[]) => {
    if (!rows.length) return '';
    const headers = Array.from(
      rows.reduce((set, row) => {
        Object.keys(row).forEach((key) => set.add(key));
        return set;
      }, new Set<string>())
    );
    const lines = [
      headers.join(','),
      ...rows.map((row) => headers.map((h) => escapeCsvValue(row[h])).join(',')),
    ];
    return lines.join('\n');
  };

  const downloadCsv = (filename: string, rows: Record<string, unknown>[]) => {
    const csv = buildCsv(rows);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const downloadExcel = async (filename: string, data: SignsReportResponse, selectedDestinations?: Set<string>) => {
    try {
      // Dynamic import to avoid loading xlsx in initial bundle
      const XLSX = await import('xlsx');

      // Prepare rows - use selected destinations if any, otherwise all
      const rows: Record<string, unknown>[] = [];

      if (selectedDestinations && selectedDestinations.size > 0 && data.signs) {
        // Export only selected destinations
        selectedDestinations.forEach((destKey) => {
          const [signIdStr, destIdStr] = destKey.split('-');
          const signId = parseInt(signIdStr, 10);
          const destId = parseInt(destIdStr, 10);
          const sign = data.signs.find((s) => s.anchor_node_id === signId);
          const destination = sign?.destinations.find((d) => d.anchor_node_id === destId);

          if (sign && destination) {
            const [lon, lat] = sign.coordinates || [null, null];
            const status = sign.status && sign.status.length > 0 ? sign.status[0] : null;

            rows.push({
              'Sign Anchor ID': sign.anchor_node_id,
              'Sign Navn': sign.name || '',
              'Sign Type': sign.is_endpoint ? 'Endepunkt' : sign.is_junction ? 'Kryss' : 'Node',
              'Sign Latitude': lat,
              'Sign Longitude': lon,
              'Destination Anchor ID': destination.anchor_node_id,
              'Destination Navn': destination.name,
              'Distance (m)': destination.distance_meters,
              'Distance (km)': destination.distance_meters ? (destination.distance_meters / 1000).toFixed(2) : '',
              'Direction': status?.direction || '',
              'Status': status?.status || '',
              'Last Inspected': status?.last_inspected || '',
              'Notes': status?.notes || '',
              'Updated By': status?.updated_by || '',
              'Updated At': status?.updated_at || '',
            });
          }
        });
      } else {
        // Export all destinations from all signs
        data.signs.forEach((sign) => {
          const [lon, lat] = sign.coordinates || [null, null];
          const status = sign.status && sign.status.length > 0 ? sign.status[0] : null;

          sign.destinations.forEach((destination) => {
            rows.push({
              'Sign Anchor ID': sign.anchor_node_id,
              'Sign Navn': sign.name || '',
              'Sign Type': sign.is_endpoint ? 'Endepunkt' : sign.is_junction ? 'Kryss' : 'Node',
              'Sign Latitude': lat,
              'Sign Longitude': lon,
              'Destination Anchor ID': destination.anchor_node_id,
              'Destination Navn': destination.name,
              'Distance (m)': destination.distance_meters,
              'Distance (km)': destination.distance_meters ? (destination.distance_meters / 1000).toFixed(2) : '',
              'Direction': status?.direction || '',
              'Status': status?.status || '',
              'Last Inspected': status?.last_inspected || '',
              'Notes': status?.notes || '',
              'Updated By': status?.updated_by || '',
              'Updated At': status?.updated_at || '',
            });
          });
        });
      }

      // Create workbook and worksheet
      const worksheet = XLSX.utils.json_to_sheet(rows);
      const workbook = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(workbook, worksheet, 'Skilt');

      // Write file
      XLSX.writeFile(workbook, filename);
      notificationManager.success('Excel-fil eksportert');
    } catch (error) {
      const appError = handleApiError(error, 'Excel Export');
      notificationManager.error(`Kunne ikke eksportere Excel: ${appError.message}`);
    }
  };

  const handleDownloadExcel = async (mode: 'route' | 'prefix') => {
    if (!signsReport) {
      notificationManager.warning('Ingen skilt-data å eksportere');
      return;
    }

    try {
      if (mode === 'route') {
        if (!routeNumber) return;
        await downloadExcel(
          `${routeNumber}-signs.xlsx`,
          signsReport,
          selectedSignDestinations.size > 0 ? selectedSignDestinations : undefined
        );
      } else {
        if (!signsPrefix || signsPrefix.trim().length === 0) return;
        await downloadExcel(
          `${signsPrefix}-signs.xlsx`,
          signsReport,
          selectedSignDestinations.size > 0 ? selectedSignDestinations : undefined
        );
      }
    } catch (error) {
      const appError = handleApiError(error, 'Signs Excel Export');
      notificationManager.error(`Kunne ikke eksportere Excel: ${appError.message}`);
    }
  };

  const handleLoadRouteSigns = async () => {
    if (!routeNumber) return;
    setIsLoadingSigns(true);
    setSignsError(null);
    try {
      const result = await api.getRouteSigns(routeNumber);
      setSignsReport(result);
    } catch (error) {
      const appError = handleApiError(error, 'Route Signs');
      setSignsError(appError.message);
      notificationManager.error(`Kunne ikke laste skilt: ${appError.message}`);
    } finally {
      setIsLoadingSigns(false);
    }
  };

  const handleLoadPrefixSigns = async () => {
    if (!signsPrefix || signsPrefix.trim().length === 0) return;
    setIsLoadingSigns(true);
    setSignsError(null);
    try {
      const result = await api.getSignsByPrefix(signsPrefix.trim());
      setSignsReport(result);
    } catch (error) {
      const appError = handleApiError(error, 'Prefix Signs');
      setSignsError(appError.message);
      notificationManager.error(`Kunne ikke laste skilt: ${appError.message}`);
    } finally {
      setIsLoadingSigns(false);
    }
  };

  const handleLoadMissingSigns = async () => {
    if (!signsPrefix || signsPrefix.trim().length === 0) return;
    setIsLoadingMissingSigns(true);
    try {
      const result = await api.getSignsMissing(signsPrefix.trim());
      setSignsMissing(result);
    } catch (error) {
      const appError = handleApiError(error, 'Missing Signs');
      notificationManager.error(`Kunne ikke laste manglende skilt: ${appError.message}`);
    } finally {
      setIsLoadingMissingSigns(false);
    }
  };

  const handleDownloadProductionCsv = async (mode: 'route' | 'prefix') => {
    try {
      if (mode === 'route') {
        if (!routeNumber) return;
        const result = await api.getRouteSignsProduction(routeNumber);
        downloadCsv(`${routeNumber}-signs-production.csv`, result.rows);
      } else {
        if (!signsPrefix || signsPrefix.trim().length === 0) return;
        const result = await api.getSignsProductionByPrefix(signsPrefix.trim());
        downloadCsv(`${signsPrefix}-signs-production.csv`, result.rows);
      }
    } catch (error) {
      const appError = handleApiError(error, 'Signs Production');
      notificationManager.error(`Kunne ikke eksportere produksjon CSV: ${appError.message}`);
    }
  };

  const formatDistanceKm = (distanceMeters?: number) => {
    if (distanceMeters === undefined || distanceMeters === null) return '';
    const km = distanceMeters / 1000;
    if (km > 5) {
      return `${Math.round(km)}km`;
    }
    return `${(Math.round(km * 2) / 2).toFixed(1)}km`;
  };

  const selectedEvent = selectedFeatureId && changeset
    ? events.find((e) => {
        const event = e.event;
        if (isSegmentUpdateGeomEvent(event) || isSegmentAddEvent(event) || event.type === 'segment.update_attrs') {
          if (isSegmentUpdateGeomEvent(event) || event.type === 'segment.update_attrs') {
            return (event as { target?: { id?: string } }).target?.id === selectedFeatureId;
          }
          if (isSegmentAddEvent(event)) {
            return event.temp_id.includes(selectedFeatureId);
          }
        }
        return false;
      })
    : null;

  const extractTarget = (event: LocalEvent | ChangeEvent): string => {
    const payload = 'event' in event ? event.event : event;
    if ('target' in payload && payload.target) {
      const target = payload.target as { kind?: string; id?: string; temp_id?: string };
      if (target.id) return `${target.kind || 'segment'}:${target.id}`;
      if (target.temp_id) return `${target.kind || 'segment'}:${target.temp_id}`;
    }
    if ('temp_id' in payload && payload.temp_id) {
      return `segment:${payload.temp_id}`;
    }
    return 'n/a';
  };

  const extractDetails = (event: LocalEvent | ChangeEvent): string => {
    const payload = 'event' in event ? event.event : event;
    const eventType = payload.type;
    if (eventType === 'segment.update_attrs') {
      const patch = (payload as { patch?: unknown }).patch;
      return patch ? JSON.stringify(patch) : '';
    }
    if (eventType === 'segment.update_geom') {
      return 'geometry updated';
    }
    if (eventType === 'segment.add') {
      return 'segment added';
    }
    if (eventType === 'segment.retire') {
      return 'segment retired';
    }
    if (eventType === 'segment.delete_new') {
      return 'new segment deleted';
    }
    return '';
  };

  const changesRows: Array<{ kind: string; type: string; target: string; details: string; ts?: string }> = [
    ...localEvents.map((event) => ({
      kind: 'lokal',
      type: event.type,
      target: extractTarget(event),
      details: extractDetails(event),
    })),
    ...events.map((event) => ({
      kind: 'changeset',
      type: event.event.type,
      target: extractTarget(event),
      details: extractDetails(event),
      ts: event.ts,
    })),
  ];
  
  // Extract segment attributes from properties
  // Properties from effective/diff layer contain the current attributes
  const segmentAttributes = selectedFeatureProperties 
    ? {
        rutenummer: selectedFeatureProperties.rutenummer || selectedFeatureProperties.route_ref,
        rutenavn: selectedFeatureProperties.rutenavn || selectedFeatureProperties.name,
        vedlikeholdsansvarlig: selectedFeatureProperties.vedlikeholdsansvarlig,
        rutetype: selectedFeatureProperties.rutetype,
        gradering: selectedFeatureProperties.gradering,
        ...selectedFeatureProperties, // Include all other properties
      } as Record<string, unknown>
    : null;

  // Calculate common attributes for bulk edit (attributes that are the same across all selected segments)
  const getCommonAttributes = (): Record<string, unknown> => {
    if (selectedFeaturesMap.size === 0) return {};
    
    const allAttributes = Array.from(selectedFeaturesMap.values());
    if (allAttributes.length === 0) return {};
    
    // Find attributes that are the same across all selected segments
    const commonAttrs: Record<string, unknown> = {};
    const firstAttrs = allAttributes[0];
    
    for (const key of Object.keys(firstAttrs)) {
      // Skip internal fields
      if (key === 'op' || key === 'id' || key === 'objid' || key === 'segment_objid' || key === 'link_id') {
        continue;
      }
      
      const value = firstAttrs[key];
      // Check if all segments have the same value for this attribute
      const allSame = allAttributes.every(attrs => {
        const normalizedValue = attrs[key];
        // Normalize for comparison (handle route_ref/rutenummer, name/rutenavn)
        if (key === 'rutenummer' || key === 'route_ref') {
          return (attrs.rutenummer || attrs.route_ref) === (value || firstAttrs.route_ref);
        }
        if (key === 'rutenavn' || key === 'name') {
          return (attrs.rutenavn || attrs.name) === (value || firstAttrs.name);
        }
        return normalizedValue === value;
      });
      
      if (allSame && value !== undefined && value !== null && value !== '') {
        // Normalize field names
        if (key === 'route_ref') {
          commonAttrs.rutenummer = value;
        } else if (key === 'name') {
          commonAttrs.rutenavn = value;
        } else {
          commonAttrs[key] = value;
        }
      }
    }
    
    return commonAttrs;
  };
  
  const commonAttributes = selectedFeatureIds.size > 1 ? getCommonAttributes() : {};

  return (
    <>
      {/* Toggle button - shown when panel is closed */}
      {!isOpen && (
        <button
          className="info-panel-toggle"
          onClick={() => setIsOpen(true)}
          aria-label="Åpne informasjonspanel"
          title="Åpne informasjonspanel"
        >
          ☰
        </button>
      )}

      {/* Info Panel */}
      <div className={`info-panel ${isOpen ? 'info-panel-open' : ''}`}>
        <div className="info-panel-header">
          <h2 className="info-panel-title">
            {changeset 
              ? `Redigering: ${routeNumber || 'Rute'}` 
              : routeNumber 
                ? `Rute: ${routeNumber}` 
                : 'Informasjon'}
          </h2>
          <button
            className="info-panel-close"
            onClick={() => setIsOpen(false)}
            aria-label="Lukk panel"
          >
            ×
          </button>
        </div>

        <div className="info-panel-content">
          {/* Mode-specific content */}
          {activeMode === 'property-ownership' && (
            <div className="info-panel-section">
              <h3>🏠 Grunneierinformasjon</h3>
              {selectedGeometryForOwnership ? (
                <>
                  {isLoadingOwnership ? (
                    <div className="info-panel-item" style={{ color: '#666', fontStyle: 'italic' }}>
                      Laster grunneier-informasjon...
                    </div>
                  ) : ownershipData ? (
                    <>
                      <div className="info-panel-item">
                        <span className="info-label">Total lengde:</span>
                        <span>{ownershipData.total_length_km?.toFixed(2) || 'N/A'} km</span>
                      </div>
                      {ownershipData.matrikkelenhet_vector && ownershipData.matrikkelenhet_vector.length > 0 && (
                        <div style={{ marginTop: '0.75rem' }}>
                          <div className="info-panel-item">
                            <span className="info-label">Antall teiger:</span>
                            <span>{ownershipData.matrikkelenhet_vector.length}</span>
                          </div>
                          <div style={{ maxHeight: '300px', overflowY: 'auto', marginTop: '0.5rem' }}>
                            {ownershipData.matrikkelenhet_vector.map((item: any, idx: number) => (
                              <div key={idx} style={{ padding: '0.5rem', marginBottom: '0.5rem', border: '1px solid #ddd', borderRadius: '4px' }}>
                                <div style={{ fontWeight: 600 }}>{item.matrikkelenhet || 'N/A'}</div>
                                {item.owners && (
                                  <div style={{ fontSize: '0.85em', color: '#666', marginTop: '0.25rem' }}>
                                    Grunneier: {item.owners}
                                  </div>
                                )}
                                {item.length_meters && (
                                  <div style={{ fontSize: '0.85em', color: '#666' }}>
                                    Lengde: {(item.length_meters / 1000).toFixed(2)} km
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {ownershipData.error_summary && (
                        <div style={{ color: '#e74c3c', marginTop: '0.5rem', fontSize: '0.85em' }}>
                          {ownershipData.error_summary}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="info-panel-item" style={{ color: '#666' }}>
                      Klikk på en rute, link eller tegn et område for å se grunneier-informasjon
                    </div>
                  )}
                </>
              ) : (
                <div className="info-panel-item" style={{ color: '#666' }}>
                  Velg en rute, link eller tegn et område for å se grunneier-informasjon
                </div>
              )}
            </div>
          )}

          {activeMode === 'anchor-naming' && (
            <div className="info-panel-section">
              <h3>Anker Navngiving</h3>
              <div className="info-panel-item" style={{ color: '#666' }}>
                Klikk på et anker på kartet for å gi det et navn
              </div>
            </div>
          )}

          {activeMode === 'signs' && (
            <div className="info-panel-section">
              <h3>Skilt</h3>
              <div className="info-panel-actions" style={{ marginBottom: '0.75rem' }}>
                <button
                  onClick={async () => {
                    if (!signsReport) {
                      notificationManager.warning('Ingen skilt-data å eksportere');
                      return;
                    }
                    try {
                      await downloadExcel(
                        'alle-skilt.xlsx',
                        signsReport,
                        undefined // Export all
                      );
                    } catch (error) {
                      const appError = handleApiError(error, 'Signs Excel Export');
                      notificationManager.error(`Kunne ikke eksportere Excel: ${appError.message}`);
                    }
                  }}
                  disabled={!signsReport}
                  className="btn btn-primary"
                  style={{ fontSize: '1em', padding: '8px 16px' }}
                >
                  📥 Last ned alle skilt (Excel)
                </button>
              </div>
              {signsReport && (
                <div style={{ marginTop: '0.75rem' }}>
                  <div className="info-panel-item">
                    <span className="info-label">Skilt:</span>
                    <span>{signsReport.totals.sign_count ?? signsReport.signs.length}</span>
                  </div>
                  <div className="info-panel-item">
                    <span className="info-label">Destinasjoner:</span>
                    <span>{signsReport.totals.destination_count ?? '-'}</span>
                  </div>
                </div>
              )}
              {selectedSignDestinations.size > 0 && signsReport && (
                <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid #ddd' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <h4 style={{ margin: 0 }}>
                      Valgte Skilt ({selectedSignDestinations.size} destinasjoner)
                    </h4>
                    <button
                      onClick={async () => {
                        if (!signsReport) return;
                        try {
                          await downloadExcel(
                            'valgte-skilt.xlsx',
                            signsReport,
                            selectedSignDestinations
                          );
                        } catch (error) {
                          const appError = handleApiError(error, 'Signs Excel Export');
                          notificationManager.error(`Kunne ikke eksportere Excel: ${appError.message}`);
                        }
                      }}
                      className="btn btn-primary"
                      style={{ fontSize: '0.9em', padding: '6px 12px' }}
                      title="Last ned valgte skilt som Excel"
                    >
                      📥 Last ned
                    </button>
                  </div>
                  <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                    {Array.from(selectedSignDestinations).map((destKey) => {
                      const [signIdStr, destIdStr] = destKey.split('-');
                      const signId = parseInt(signIdStr, 10);
                      const destId = parseInt(destIdStr, 10);
                      const sign = signsReport.signs.find((s) => s.anchor_node_id === signId);
                      const destination = sign?.destinations.find((d) => d.anchor_node_id === destId);

                      if (!sign || !destination) return null;

                      return (
                        <div
                          key={destKey}
                          style={{
                            padding: '0.5rem',
                            marginBottom: '0.5rem',
                            border: '1px solid #ddd',
                            borderRadius: '4px',
                            backgroundColor: '#f9f9f9',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontWeight: 600, fontSize: '0.9em' }}>
                                {sign.name || `Anchor ${sign.anchor_node_id}`} → {destination.name}
                              </div>
                              <div style={{ fontSize: '0.85em', color: '#666', marginTop: '0.25rem' }}>
                                {sign.is_endpoint ? 'Endepunkt' : sign.is_junction ? 'Kryss' : 'Node'} ·{' '}
                                {formatDistanceKm(destination.distance_meters)}
                              </div>
                            </div>
                            <button
                              onClick={() => {
                                if (onSignDestinationSelect) {
                                  onSignDestinationSelect(destKey, false);
                                }
                              }}
                              style={{
                                marginLeft: '0.5rem',
                                padding: '0.25rem 0.5rem',
                                fontSize: '0.85em',
                                backgroundColor: '#e74c3c',
                                color: 'white',
                                border: 'none',
                                borderRadius: '4px',
                                cursor: 'pointer',
                              }}
                              title="Fjern fra valgte"
                            >
                              ×
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Route information - shown in inspection and edit modes */}
          {(activeMode === 'inspection' || activeMode === 'edit') && routeNumber && (
            <>
              {/* Route information - always shown when route is selected */}
              {routeNumber && (
                <div className="info-panel-section">
                  <h3>Rute: {routeNumber}</h3>
                  {routeMetadata ? (
                    <>
                      {routeMetadata.rutenavn && (
                        <div className="info-panel-item">
                          <span className="info-label">Rutenavn:</span>
                          <span>{String(routeMetadata.rutenavn)}</span>
                        </div>
                      )}
                      {routeMetadata.vedlikeholdsansvarlig && (
                        <div className="info-panel-item">
                          <span className="info-label">Vedlikeholdsansvarlig:</span>
                          <span>{String(routeMetadata.vedlikeholdsansvarlig)}</span>
                        </div>
                      )}
                      {routeMetadata.rutetype && (
                        <div className="info-panel-item">
                          <span className="info-label">Rutetype:</span>
                          <span>{String(routeMetadata.rutetype)}</span>
                        </div>
                      )}
                      {routeMetadata.gradering && (
                        <div className="info-panel-item">
                          <span className="info-label">Gradering:</span>
                          <span>{String(routeMetadata.gradering)}</span>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="info-panel-item" style={{ color: '#666', fontStyle: 'italic' }}>
                      Laster rute-metadata...
                    </div>
                  )}
                </div>
              )}

              {/* Changeset section - only when changeset exists */}
              {changeset && (
            <>
              {/* Changeset metadata */}
              <div className="info-panel-section">
                <h3>Changeset</h3>
                <div className="info-panel-item">
                  <span className="info-label">Tittel:</span>
                  <span>{changeset.title}</span>
                </div>
                {changeset.description && (
                  <div className="info-panel-item">
                    <span className="info-label">Beskrivelse:</span>
                    <span>{changeset.description}</span>
                  </div>
                )}
                <div className="info-panel-item">
                  <span className="info-label">Status:</span>
                  <span className={`status-badge status-${changeset.status}`}>
                    {changeset.status}
                  </span>
                </div>
                <div className="info-panel-item">
                  <span className="info-label">Events:</span>
                  <span>{events.length}</span>
                </div>
                {changeset.pr_url && (
                  <div className="info-panel-item">
                    <span className="info-label">PR:</span>
                    <a href={changeset.pr_url} target="_blank" rel="noopener noreferrer">
                      Vis PR
                    </a>
                  </div>
                )}
              </div>

              {/* Changeset Actions - only when changeset exists */}
              <div className="info-panel-section">
                <h3>Changeset Handlinger</h3>
                <div className="info-panel-actions">
                  <button
                    onClick={handleValidate}
                    disabled={isValidating || changeset.status !== 'draft'}
                    className="btn btn-primary"
                  >
                    {isValidating ? 'Validerer...' : 'Valider Changeset'}
                  </button>
                  {onSaveChanges && (
                    <button
                      onClick={onSaveChanges}
                      disabled={loading}
                      className="btn btn-secondary"
                      title="Eksporter changeset til JSON-fil"
                    >
                      💾 Eksporter til fil
                    </button>
                  )}
                  {changeset && (
                    <button
                      onClick={async () => {
                        try {
                          const blob = await api.downloadChangesetArtifact(changeset.id, 'diff.json');
                          const url = URL.createObjectURL(blob);
                          const link = document.createElement('a');
                          link.href = url;
                          link.download = `changeset-${changeset.id}-diff.json`;
                          document.body.appendChild(link);
                          link.click();
                          document.body.removeChild(link);
                          URL.revokeObjectURL(url);
                          notificationManager.success('JSON eksport lastet ned');
                        } catch (error: unknown) {
                          const appError = handleApiError(error, 'Export JSON');
                          notificationManager.error(`Kunne ikke eksportere JSON: ${appError.message}`);
                        }
                      }}
                      disabled={loading}
                      className="btn btn-secondary"
                      title="Eksporter endringer som JSON (backend)"
                    >
                      📦 Eksporter JSON
                    </button>
                  )}
                  <button
                    onClick={handlePublish}
                    disabled={isPublishing || (changeset && changeset.status !== 'draft') || loading}
                    className="btn btn-success"
                  >
                    {isPublishing || loading ? 'Publiserer...' : '📤 Send til Review'}
                  </button>
                </div>
              </div>

                  {/* Validation results */}
                  {validation && (
                    <div className="info-panel-section">
                      <h3>Validering</h3>
                      {validation.errors.length > 0 && (
                        <div className="validation-errors">
                          <strong style={{ color: '#e74c3c' }}>
                            Feil ({validation.errors.length}):
                          </strong>
                          <ul>
                            {validation.errors.map((err, i) => (
                              <li key={i} style={{ color: '#e74c3c' }}>
                                {err.message} ({err.code})
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {validation.warnings.length > 0 && (
                        <div className="validation-warnings">
                          <strong style={{ color: '#f39c12' }}>
                            Advarsler ({validation.warnings.length}):
                          </strong>
                          <ul>
                            {validation.warnings.map((warn, i) => (
                              <li key={i} style={{ color: '#f39c12' }}>
                                {warn.message} ({warn.code})
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {validation.errors.length === 0 && validation.warnings.length === 0 && (
                        <div style={{ color: '#2ecc71' }}>✓ Ingen problemer funnet</div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* Route validation (when route is selected - available without changeset) */}
              {routeNumber && (
                <div className="info-panel-section">
                  <h3>Rutevalidering</h3>
                  <div className="info-panel-actions" style={{ marginBottom: '0.75rem' }}>
                    <button
                      onClick={handleValidateRoute}
                      disabled={isLoadingRouteValidation}
                      className="btn btn-primary"
                    >
                      {isLoadingRouteValidation ? 'Validerer...' : 'Valider Rute'}
                    </button>
                  </div>
                  {routeValidation && (
                    <>
                      <div className="info-panel-item">
                        <span className="info-label">Status:</span>
                        <span className={`status-badge status-${routeValidation.status.toLowerCase()}`}>
                          {routeValidation.status}
                        </span>
                      </div>
                      <div className="info-panel-item">
                        <span className="info-label">Segmenter:</span>
                        <span>{routeValidation.segment_count}</span>
                      </div>
                      <div className="info-panel-item">
                        <span className="info-label">Linker:</span>
                        <span>{routeValidation.link_count}</span>
                      </div>
                      
                      {routeValidation.errors.length > 0 && (
                        <div className="validation-errors" style={{ marginTop: '1rem' }}>
                          <strong style={{ color: '#e74c3c' }}>
                            Feil ({routeValidation.errors.length}):
                          </strong>
                          <ul style={{ marginTop: '0.5rem', paddingLeft: '1.5rem' }}>
                            {routeValidation.errors.map((err, i) => (
                              <li key={i} style={{ color: '#e74c3c', marginBottom: '0.25rem' }}>
                                <strong>{err.type}:</strong> {err.message}
                                {err.affected_segments && err.affected_segments.length > 0 && (
                                  <span style={{ fontSize: '0.85em', color: '#999' }}>
                                    {' '}(Segmenter: {err.affected_segments.join(', ')})
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      
                      {routeValidation.warnings.length > 0 && (
                        <div className="validation-warnings" style={{ marginTop: '1rem' }}>
                          <strong style={{ color: '#f39c12' }}>
                            Advarsler ({routeValidation.warnings.length}):
                          </strong>
                          <ul style={{ marginTop: '0.5rem', paddingLeft: '1.5rem' }}>
                            {routeValidation.warnings.map((warn, i) => (
                              <li key={i} style={{ color: '#f39c12', marginBottom: '0.25rem' }}>
                                <strong>{warn.type}:</strong> {warn.message}
                                {warn.affected_segments && warn.affected_segments.length > 0 && (
                                  <span style={{ fontSize: '0.85em', color: '#999' }}>
                                    {' '}(Segmenter: {warn.affected_segments.join(', ')})
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      
                      {routeValidation.errors.length === 0 && routeValidation.warnings.length === 0 && (
                        <div style={{ color: '#2ecc71', marginTop: '1rem' }}>✓ Ingen problemer funnet</div>
                      )}
                    </>
                  )}
                </div>
              )}

                  {/* Signs report - only in inspection mode */}
                  {activeMode === 'inspection' && (
                    <div className="info-panel-section">
                      <h3>Skilt</h3>
                <div className="info-panel-item">
                  <span className="info-label">Områdeprefix:</span>
                  <input
                    type="text"
                    value={signsPrefix}
                    onChange={(event) => {
                      setSignsPrefix(event.target.value);
                      if (onSignsPrefixChange) {
                        onSignsPrefixChange(event.target.value);
                      }
                    }}
                    placeholder="bre"
                    style={{ width: '120px' }}
                  />
                </div>
                <div className="info-panel-actions" style={{ marginTop: '0.5rem' }}>
                  <button
                    onClick={handleLoadPrefixSigns}
                    disabled={isLoadingSigns || !signsPrefix.trim()}
                    className="btn btn-primary"
                  >
                    {isLoadingSigns ? 'Laster...' : 'Last område-skilt'}
                  </button>
                  <button
                    onClick={handleLoadMissingSigns}
                    disabled={isLoadingMissingSigns || !signsPrefix.trim()}
                    className="btn btn-secondary"
                  >
                    {isLoadingMissingSigns ? 'Laster...' : 'Manglende skilt'}
                  </button>
                  <button
                    onClick={() => handleDownloadProductionCsv('prefix')}
                    disabled={!signsPrefix.trim()}
                    className="btn btn-secondary"
                  >
                    📄 Produksjon CSV (område)
                  </button>
                  <button
                    onClick={() => handleDownloadExcel('prefix')}
                    disabled={!signsPrefix.trim() || !signsReport}
                    className="btn btn-secondary"
                  >
                    📊 Eksporter Excel (område)
                  </button>
                  {routeNumber && (
                    <>
                      <button
                        onClick={handleLoadRouteSigns}
                        disabled={isLoadingSigns}
                        className="btn btn-primary"
                      >
                        {isLoadingSigns ? 'Laster...' : `Last rute-skilt (${routeNumber})`}
                      </button>
                      <button
                        onClick={() => handleDownloadProductionCsv('route')}
                        className="btn btn-secondary"
                      >
                        📄 Produksjon CSV (rute)
                      </button>
                      <button
                        onClick={() => handleDownloadExcel('route')}
                        disabled={!signsReport}
                        className="btn btn-secondary"
                      >
                        📊 Eksporter Excel (rute)
                      </button>
                    </>
                  )}
                </div>

                {signsError && (
                  <div style={{ color: '#e74c3c', marginTop: '0.5rem' }}>
                    {signsError}
                  </div>
                )}

                {signsReport && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <div className="info-panel-item">
                      <span className="info-label">Skilt:</span>
                      <span>{signsReport.totals.sign_count ?? signsReport.signs.length}</span>
                    </div>
                    <div className="info-panel-item">
                      <span className="info-label">Destinasjoner:</span>
                      <span>{signsReport.totals.destination_count ?? '-'}</span>
                    </div>
                    <div style={{ marginTop: '0.5rem', maxHeight: '240px', overflowY: 'auto' }}>
                      {signsReport.signs.map((sign) => (
                        <div key={sign.anchor_node_id} style={{ marginBottom: '0.5rem' }}>
                          <div style={{ fontWeight: 600 }}>
                            {sign.anchor_node_id} · {sign.name || 'Uten navn'} ·{' '}
                            {sign.is_endpoint ? 'Endepunkt' : sign.is_junction ? 'Kryss' : 'Node'}
                          </div>
                          <div style={{ fontSize: '0.85em', color: '#555' }}>
                            Destinasjoner:{' '}
                            {sign.destinations.length > 0
                              ? sign.destinations
                                  .map((dest) => `${dest.name} (${formatDistanceKm(dest.distance_meters)})`)
                                  .join(', ')
                              : 'Ingen'}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {signsMissing && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <div className="info-panel-item">
                      <span className="info-label">Mangler destinasjoner:</span>
                      <span>{signsMissing.missing_destinations.length}</span>
                    </div>
                    <div className="info-panel-item">
                      <span className="info-label">Mangler navn:</span>
                      <span>{signsMissing.missing_anchor_names.length}</span>
                    </div>
                  </div>
                )}

                {/* Selected sign destinations */}
                {selectedSignDestinations.size > 0 && signsReport && (
                  <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid #ddd' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                      <h4 style={{ margin: 0 }}>
                        Valgte Skilt ({selectedSignDestinations.size} destinasjoner)
                      </h4>
                      <button
                        onClick={async () => {
                          if (!signsReport) return;
                          try {
                            await downloadExcel(
                              'valgte-skilt.xlsx',
                              signsReport,
                              selectedSignDestinations
                            );
                          } catch (error) {
                            const appError = handleApiError(error, 'Signs Excel Export');
                            notificationManager.error(`Kunne ikke eksportere Excel: ${appError.message}`);
                          }
                        }}
                        className="btn btn-primary"
                        style={{ fontSize: '0.85rem', padding: '4px 8px' }}
                        title="Last ned valgte skilt som Excel"
                      >
                        📥 Last ned
                      </button>
                    </div>
                    <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                      {Array.from(selectedSignDestinations).map((destKey) => {
                        const [signIdStr, destIdStr] = destKey.split('-');
                        const signId = parseInt(signIdStr, 10);
                        const destId = parseInt(destIdStr, 10);
                        const sign = signsReport.signs.find((s) => s.anchor_node_id === signId);
                        const destination = sign?.destinations.find((d) => d.anchor_node_id === destId);

                        if (!sign || !destination) return null;

                        return (
                          <div
                            key={destKey}
                            style={{
                              padding: '0.5rem',
                              marginBottom: '0.5rem',
                              border: '1px solid #ddd',
                              borderRadius: '4px',
                              backgroundColor: '#f9f9f9',
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                              <div style={{ flex: 1 }}>
                                <div style={{ fontWeight: 600, fontSize: '0.9em' }}>
                                  {sign.name || `Anchor ${sign.anchor_node_id}`} → {destination.name}
                                </div>
                                <div style={{ fontSize: '0.85em', color: '#666', marginTop: '0.25rem' }}>
                                  {sign.is_endpoint ? 'Endepunkt' : sign.is_junction ? 'Kryss' : 'Node'} ·{' '}
                                  {formatDistanceKm(destination.distance_meters)}
                                </div>
                              </div>
                              <button
                                onClick={() => {
                                  if (onSignDestinationSelect) {
                                    onSignDestinationSelect(destKey, false);
                                  }
                                }}
                                style={{
                                  marginLeft: '0.5rem',
                                  padding: '0.25rem 0.5rem',
                                  fontSize: '0.85em',
                                  backgroundColor: '#e74c3c',
                                  color: 'white',
                                  border: 'none',
                                  borderRadius: '4px',
                                  cursor: 'pointer',
                                }}
                                title="Fjern fra valgte"
                              >
                                ×
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                    </div>
                  )}
                </>
              )}

              {/* Route editing (when route is selected but no segment) - only in edit mode */}
              {activeMode === 'edit' && !selectedFeatureId && routeNumber && (
                <div className="info-panel-section">
                  <h3 style={{ margin: 0, marginBottom: '0.75rem' }}>Rediger Rute</h3>
                  
                  {showRouteEditForm ? (
                    <RouteEditForm
                      changeset={changeset}
                      routeNumber={routeNumber}
                      currentAttributes={(routeMetadata || {}) as Record<string, unknown>}
                      onEventAdded={onFeatureUpdate as ((event: SegmentUpdateAttrsEvent) => void) | undefined}
                      onSave={() => {
                        setShowRouteEditForm(false);
                        if (onFeatureUpdate) {
                          onFeatureUpdate();
                        }
                        if (changeset) {
                          onChangesetUpdate();
                        }
                        // Reload route metadata
                        api.getRoute(routeNumber, false)
                          .then((data) => {
                            setRouteMetadata({
                              rutenummer: data.rutenummer,
                              rutenavn: data.rutenavn,
                              vedlikeholdsansvarlig: data.vedlikeholdsansvarlig,
                              rutetype: data.rutetype,
                              gradering: data.gradering,
                            });
                          })
                          .catch(() => {
                            // Ignore errors
                          });
                      }}
                      onCancel={() => setShowRouteEditForm(false)}
                    />
                  ) : (
                    <button
                      onClick={() => setShowRouteEditForm(true)}
                      className="btn btn-secondary"
                      style={{ marginTop: '0.5rem' }}
                    >
                      Rediger rute-metadata
                    </button>
                  )}
                </div>
              )}

              {/* Selected features - Multi-select - only in edit mode */}
              {activeMode === 'edit' && selectedFeatureIds.size > 1 && (
                <div className="info-panel-section">
                  <h3 style={{ margin: 0, marginBottom: '0.75rem' }}>
                    {selectedFeatureIds.size} valgte elementer
                  </h3>
                  
                  {showBulkEditForm ? (
                    <BulkSegmentEditForm
                      changeset={changeset}
                      segmentIds={Array.from(selectedFeatureIds)}
                      currentAttributes={commonAttributes}
                      onEventAdded={onFeatureUpdate as ((event: SegmentUpdateAttrsEvent) => void) | undefined}
                      onSave={() => {
                        setShowBulkEditForm(false);
                        if (onFeatureUpdate) {
                          onFeatureUpdate();
                        }
                        if (changeset) {
                          onChangesetUpdate();
                        }
                      }}
                      onCancel={() => setShowBulkEditForm(false)}
                    />
                  ) : (
                    <>
                      <div className="info-panel-item">
                        <span className="info-label">Antall valgte:</span>
                        <span>{selectedFeatureIds.size} segmenter</span>
                      </div>
                      {Object.keys(commonAttributes).length > 0 && (
                        <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: '#666' }}>
                          <strong>Felles attributter:</strong>
                          <ul style={{ margin: '0.25rem 0', paddingLeft: '1.5rem' }}>
                            {commonAttributes.rutenummer && (
                              <li>Rutenummer: {String(commonAttributes.rutenummer)}</li>
                            )}
                            {commonAttributes.rutenavn && (
                              <li>Rutenavn: {String(commonAttributes.rutenavn)}</li>
                            )}
                            {commonAttributes.vedlikeholdsansvarlig && (
                              <li>Vedlikeholdsansvarlig: {String(commonAttributes.vedlikeholdsansvarlig)}</li>
                            )}
                            {commonAttributes.rutetype && (
                              <li>Rutetype: {String(commonAttributes.rutetype)}</li>
                            )}
                            {commonAttributes.gradering && (
                              <li>Gradering: {String(commonAttributes.gradering)}</li>
                            )}
                          </ul>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* Events list - only when changeset exists */}
              {changeset && (
                <>
                  <div className="info-panel-section">
                    <h3>Events ({events.length})</h3>
                    <div className="events-list">
                      {events.map((event) => (
                        <div key={event.event_id} className="event-item">
                          <div className="event-type">{event.event.type}</div>
                          <div className="event-time">
                            {new Date(event.ts).toLocaleString()}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                  {/* Changes for route - only when changeset exists */}
                  {routeNumber && (
                    <div className="info-panel-section">
                      <h3>Endringer for rute</h3>
                      {changesRows.length === 0 ? (
                        <div style={{ color: '#666', fontStyle: 'italic' }}>
                          Ingen registrerte endringer
                        </div>
                      ) : (
                        <div style={{ overflowX: 'auto' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9em' }}>
                            <thead>
                              <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
                                <th style={{ padding: '6px 8px' }}>Type</th>
                                <th style={{ padding: '6px 8px' }}>Target</th>
                                <th style={{ padding: '6px 8px' }}>Detaljer</th>
                                <th style={{ padding: '6px 8px' }}>Når</th>
                              </tr>
                            </thead>
                            <tbody>
                              {changesRows.map((row, index) => (
                                <tr key={`${row.kind}-${row.type}-${row.target}-${index}`} style={{ borderBottom: '1px solid #f0f0f0' }}>
                                  <td style={{ padding: '6px 8px' }}>
                                    {row.type} <span style={{ color: '#999' }}>({row.kind})</span>
                                  </td>
                                  <td style={{ padding: '6px 8px' }}>{row.target}</td>
                                  <td style={{ padding: '6px 8px', color: '#555' }}>{row.details}</td>
                                  <td style={{ padding: '6px 8px' }}>
                                    {row.ts ? new Date(row.ts).toLocaleString() : '—'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* Selected feature - Single select - only in edit mode */}
              {activeMode === 'edit' && selectedFeatureId && selectedFeatureIds.size <= 1 && (
                <div className="info-panel-section">
                  <h3 style={{ margin: 0, marginBottom: '0.75rem' }}>Valgt element</h3>
              
                  {showEditForm ? (
                    <div style={{ border: '2px solid #007bff', padding: '1rem', marginTop: '0.5rem', borderRadius: '4px', backgroundColor: '#f0f8ff' }}>
                      <div style={{ marginBottom: '0.5rem', fontWeight: 'bold', color: '#007bff' }}>📝 Redigerer metadata...</div>
                      <SegmentEditForm
                        changeset={changeset}
                        segmentId={selectedFeatureId}
                        currentAttributes={segmentAttributes || {}}
                        onEventAdded={onFeatureUpdate as ((event: SegmentUpdateAttrsEvent) => void) | undefined}
                        onSave={() => {
                          setShowEditForm(false);
                          if (onFeatureUpdate) {
                            onFeatureUpdate();
                          }
                          if (changeset) {
                            onChangesetUpdate();
                          }
                        }}
                        onCancel={() => setShowEditForm(false)}
                      />
                    </div>
                  ) : (
                    <>
                      <div className="info-panel-item">
                        <span className="info-label">ID:</span>
                        <span>{selectedFeatureId}</span>
                      </div>
                      {selectedEvent && (
                        <div className="info-panel-item">
                          <span className="info-label">Event:</span>
                          <span>{selectedEvent.event.type}</span>
                        </div>
                      )}
                      {selectedFeatureProperties && (
                        <>
                          {selectedFeatureProperties.rutenummer && (
                            <div className="info-panel-item">
                              <span className="info-label">Rutenummer:</span>
                              <span>{String(selectedFeatureProperties.rutenummer)}</span>
                            </div>
                          )}
                          {selectedFeatureProperties.rutenavn && (
                            <div className="info-panel-item">
                              <span className="info-label">Rutenavn:</span>
                              <span>{String(selectedFeatureProperties.rutenavn)}</span>
                            </div>
                          )}
                          {selectedFeatureProperties.vedlikeholdsansvarlig && (
                            <div className="info-panel-item">
                              <span className="info-label">Vedlikeholdsansvarlig:</span>
                              <span>{String(selectedFeatureProperties.vedlikeholdsansvarlig)}</span>
                            </div>
                          )}
                          {selectedFeatureProperties.rutetype && (
                            <div className="info-panel-item">
                              <span className="info-label">Rutetype:</span>
                              <span>{String(selectedFeatureProperties.rutetype)}</span>
                            </div>
                          )}
                          {selectedFeatureProperties.gradering && (
                            <div className="info-panel-item">
                              <span className="info-label">Gradering:</span>
                              <span>{String(selectedFeatureProperties.gradering)}</span>
                            </div>
                          )}
                        </>
                      )}
                      <div className="info-panel-actions" style={{ marginTop: '0.75rem' }}>
                        <button
                          onClick={() => setShowEditForm(true)}
                          className="btn btn-primary"
                        >
                          Rediger metadata
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
        </div>
      </div>
    </>
  );
}
