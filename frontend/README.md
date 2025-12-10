# Stiflyt Frontend

A Leaflet-based frontend for visualizing routes and property information from the Stiflyt API.

## Features

### Multiple Visualization Modes

1. **Colored Route Segments**
   - Route is split by property ownership
   - Each property segment has a unique color
   - Circular markers indicate property boundaries

2. **Property Table**
   - Sortable table showing all properties along the route
   - Shows offset (km), matrikkelenhet, bruksnavn, and length
   - Click to highlight property on map

3. **Timeline View**
   - Chronological list of properties
   - Color-coded by property
   - Shows exact position and length

4. **Interactive Map**
   - Click on route segments to see property popups
   - Circular markers at property boundaries
   - Legend showing all unique properties

## Usage

1. Start the FastAPI backend:
```bash
cd /home/otroan/stiflyt
export DB_USER=otroan
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

2. Open `index.html` in a web browser, or serve it with a simple HTTP server:
```bash
cd frontend
python3 -m http.server 8080
```

3. Navigate to `http://localhost:8080` in your browser

4. Enter a route number (e.g., "bre10") and click "Last rute"

## Design Decisions

### Property Representation

**1. Colored Route Segments**
- **Pros**: Immediate visual understanding of property boundaries
- **Cons**: Can be cluttered with many properties
- **Best for**: Overview and quick identification

**2. Circular Markers**
- **Pros**: Clear indication of property transitions
- **Cons**: May overlap on dense routes
- **Best for**: Navigation and precise location finding

**3. Property Table**
- **Pros**: Complete information, sortable, searchable
- **Cons**: Requires scrolling for long routes
- **Best for**: Detailed analysis and reporting

**4. Timeline View**
- **Pros**: Chronological order, easy to follow
- **Cons**: Less spatial context
- **Best for**: Understanding sequence of properties

**5. Popups**
- **Pros**: Contextual information at click point
- **Cons**: Requires interaction
- **Best for**: Quick property lookups

### Recommended Approach

The frontend combines all approaches:
- **Primary**: Colored segments for visual overview
- **Secondary**: Table for detailed information
- **Tertiary**: Markers and popups for interactive exploration

This provides multiple ways to access the same information, catering to different use cases and user preferences.

## Future Enhancements

- [ ] Filter properties by municipality
- [ ] Search/filter in property table
- [ ] Export route data as GeoJSON/CSV
- [ ] Show property areas on map
- [ ] Elevation profile
- [ ] Print-friendly view
- [ ] Mobile-responsive design improvements

