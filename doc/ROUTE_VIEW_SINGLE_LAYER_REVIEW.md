# Code review: Single-layer route view implementation

## Summary

The implementation matches the design in `ROUTE_VIEW_SINGLE_LAYER_IMPLEMENTATION.md`: one drawn geometry at a time (route line, segments, or links), mode selector in the sidebar, and `showLinks` kept for bbox links when no route is selected. The following review checks correctness and lists improvements by priority.

---

## Follow-up changes (done)

- **Remove "Rediger rute" button:** The edit-mode toolbar (toggle "✏️ Rediger Rute" and the edit tools: draw, edit, split, delete) has been removed from MapView. Edit mode state and GeomanControl remain in the app but are no longer toggled from the map toolbar.
- **All routes visible when one is selected:**
  - **Background layer:** An "all routes" pane (`allRoutesPane`, z-index 150) draws `routesInView` with a subtle grey style (color `#95a5a6`, weight 2, opacity 0.7). It is drawn whenever `routesInView` has features, including when a single route is selected, so the rest of the network stays visible behind the selected route/segments/links.
  - **Loading:** Routes in viewport are now loaded when `showLinks || routeNumber` (previously only when `showLinks`). So when a route is selected we still fetch and display all routes in view; the selected route is drawn on top (red route pane or segments/links) so it stays visually primary.

---

## Correctness check

| Requirement | Status | Notes |
|-------------|--------|--------|
| Single layer: only route OR segments OR links drawn for selected route | OK | Route layer only when `routeViewMode === 'route'`; SegmentsLayer only when `routeViewMode === 'segments'`; LinksLayer inside overlay, shown when `routeViewMode === 'links'` (or bbox when no route). |
| `routeViewMode` state in App, passed to MapView and InfoPanel | OK | Type in `types.ts`, state and `handleRouteViewModeChange` in App. |
| Bbox links when no route: `showLinks` only | OK | `showLinksMode = routeViewMode === 'links' \|\| (!selectedRouteNumber && showLinks)`; Lenker overlay `checked` = `selectedRouteNumber ? routeViewMode === 'links' : showLinks`. |
| Mode selector in InfoPanel (Rute / Segmenter / Lenker) | OK | Radio group when `routeNumber` is set; segment list only when `routeViewMode === 'segments'`. |
| Reset to route mode on route selection | OK | `setRouteViewMode('route')` in `handleSelectRoute` when loading a route. |
| Lenker overlay toggle updates mode when route selected | OK | `handleShowLinksChange` in App sets `routeViewMode` to `'links'` or `'route'` when `selectedRouteNumber` is set. |
| Segment endpoints only in segment mode | OK | `showSegmentsMode && segmentsData` used to add segment boundary circleMarkers. |
| Anchor markers independent of mode | OK | Shown when `showAnchors`; `visibleAnchorNodes` unchanged. |
| All routes shown when one selected | OK | All-routes pane draws `routesInView` (grey); routes loaded when `showLinks \|\| routeNumber`. Selected route/segments/links drawn on higher panes. |
| "Rediger rute" toolbar removed | OK | Edit toggle and edit tools removed from MapView; no map UI to enter edit mode. |

---

## Edge cases

- **Route deselection:** When the user clears the selected route, `routeViewMode` is not reset. On the next route selection, `handleSelectRoute` sets it to `'route'`, so behavior is correct. Resetting `routeViewMode` on deselection would make state clearer (low priority).
- **LayersControl sync:** The "Lenker" overlay uses `checked={selectedRouteNumber ? routeViewMode === 'links' : showLinks}`. In react-leaflet, `checked` is mainly initial state; the checkbox is controlled by Leaflet. So if the user picks "Segmenter" or "Rute" in the sidebar, the Lenker checkbox in the layer control may stay visually checked until they click it. Our state is correct; the layer content is shown/hidden by React (SegmentsLayer vs LinksLayer), but the checkbox UX can be out of sync (see improvements below).

---

## Improvements task list (by priority)

### P1 – High (correctness / UX)

1. **Keep "Lenker" overlay checkbox in sync with sidebar mode**
   When the user changes mode in InfoPanel (e.g. to "Rute" or "Segmenter"), the Lenker overlay checkbox in the map’s layer control does not update because Leaflet owns it. Options: (a) Programmatically add/remove the overlay layer when `routeViewMode` changes so the checkbox state matches (e.g. via ref to LayersControl and Leaflet API), or (b) Document the behavior and optionally hide or repurpose the Lenker overlay when a route is selected so only the sidebar controls mode.

2. **Link endpoint markers in links mode**
   Doc §3: in links mode show "markører på linkgrenser (knutepunkter)". The endpoints effect declares `linkEndpointSet`, `linkEndpointCounts`, `linkEndpointCoords` but never draws circleMarkers for link boundaries. Segment boundaries get violet markers; link boundaries do not. Add drawing of link start/end (or node) markers when `showLinksMode` and `linksData` (e.g. from LineString coordinates), reusing the same pane/style approach as segment endpoints.

### P2 – Medium (consistency / doc alignment)

3. **Optional: route start/end markers in route mode**
   Doc §3: "route: markører kun på rutens start og slutt (evt. ingen markører)". Currently there are no markers in route mode. Either add two circleMarkers from `routeGeometry` (if LineString) when `routeViewMode === 'route'`, or add a short comment that we chose "ingen markører" for route mode.

4. **Reset `routeViewMode` on route deselection**
   In `handleSelectRoute`, when `!rutenummer`, call `setRouteViewMode('route')` so state is clean when no route is selected and the next selection starts from a known mode.

5. **Remove dead code in endpoints effect**
   Remove or use the unused variables in the endpoints `useEffect`: `linkEndpointSet`, `linkEndpointCounts`, `linkEndpointCoords`, `findAnchorAtCoord`. If link endpoint drawing is implemented (item 2), use them; otherwise remove to avoid linter noise and confusion.

### P3 – Low (code quality / maintainability)

6. **Extract route content into one component (doc §2)**
   Doc suggests one "route content" layer that switches data and style by mode. Currently: route line in a `useEffect`, SegmentsLayer, and LinksLayer are separate. Consider a single `RouteContentLayer` that takes `routeViewMode`, `routeGeometry`, `segmentsData`, `linksData`, and selection props, and renders exactly one of the three geometries with the right style. This would centralize "only one layer drawn" and simplify MapView.

7. **InfoPanel mode selector styling**
   The radio group for "Rute | Segmenter | Lenker" uses inline styles. Consider a small CSS class (e.g. in InfoPanel.css) for spacing and alignment, or a shared control component if the same pattern appears elsewhere.

8. **Pre-existing MapView linter issues**
   Two existing issues remain: StyleFunction type at L3421 (style callback signature) and `toggleDraw` on PMMap at L3521. Fix in a separate change so the single-layer work stays isolated.

---

## Summary table

| Prio | Item | Effort | Status |
|------|------|--------|--------|
| —    | Remove "Rediger rute" toolbar | Trivial | Done |
| —    | All routes background layer when route selected | Small | Done |
| —    | Load routes when `showLinks \|\| routeNumber` | Trivial | Done |
| P1   | Sync Lenker overlay checkbox with sidebar mode | Medium | Open |
| P1   | Draw link endpoint markers in links mode | Small | Open |
| P2   | Route start/end markers in route mode (or document "ingen") | Small | Open |
| P2   | Reset routeViewMode on route deselection | Trivial | Open |
| P2   | Remove or use link endpoint dead code in endpoints effect | Trivial | Open |
| P3   | Single RouteContentLayer component | Medium | Open |
| P3   | InfoPanel mode selector CSS | Trivial | Open |
| P3   | Fix pre-existing MapView linter errors | Small | Open |

Overall the change is correct and matches the plan. "Rediger rute" is removed and all routes remain visible when one is selected. Remaining follow-ups: overlay checkbox sync (P1) and link boundary markers (P1).
