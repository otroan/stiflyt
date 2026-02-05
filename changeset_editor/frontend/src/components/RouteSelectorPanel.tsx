import React from 'react';
import './RouteSelectorPanel.css';

interface Route {
  rutenummer: string;
  rutenavn: string | null;
  totalKm?: number;
}

interface RouteSelectorPanelProps {
  routes: Route[];
  position: { x: number; y: number };
  onRouteSelect: (rutenummer: string) => void;
  onClose: () => void;
  currentIndex?: number;
  onNavigate?: (direction: 'prev' | 'next') => void;
}

export function RouteSelectorPanel({
  routes,
  position,
  onRouteSelect,
  onClose,
  currentIndex = 0,
  onNavigate,
}: RouteSelectorPanelProps) {
  if (routes.length === 0) return null;

  return (
    <div
      className="route-selector-panel"
      style={{
        position: 'fixed',
        left: `${position.x}px`,
        top: `${position.y}px`,
        zIndex: 10000,
        transform: 'translate(-50%, -100%)',
        marginTop: '-10px',
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onMouseEnter={(e) => {
        e.stopPropagation();
        // Keep panel open when mouse enters panel - cancel any pending close
      }}
      onMouseLeave={(e) => {
        e.stopPropagation();
        // When mouse leaves panel, close it after a short delay
        // This gives time for mouse to move back to panel if needed
        setTimeout(() => {
          const panelElement = document.querySelector('.route-selector-panel');
          if (panelElement && !panelElement.matches(':hover') && !panelElement.querySelector(':hover')) {
            onClose();
          }
        }, 150);
      }}
    >
      <div className="route-selector-header">
        <div className="route-selector-title">Velg rute:</div>
        <button className="route-selector-close" onClick={onClose} title="Lukk">
          ×
        </button>
      </div>

      <div className="route-selector-routes">
        {routes.map((route, index) => (
          <div
            key={route.rutenummer}
            className={`route-selector-item ${index === currentIndex ? 'active' : ''}`}
            onClick={() => onRouteSelect(route.rutenummer)}
          >
            <div className="route-selector-item-number">{route.rutenummer}</div>
            <div className="route-selector-item-name">{route.rutenavn || 'Uten navn'}</div>
            {route.totalKm && (
              <div className="route-selector-item-km">{route.totalKm.toFixed(1)} km</div>
            )}
          </div>
        ))}
      </div>

      {routes.length > 1 && onNavigate && (
        <div className="route-selector-navigation">
          <button
            className="route-selector-nav-btn"
            onClick={() => onNavigate('prev')}
            disabled={currentIndex === 0}
            title="Forrige rute"
          >
            ‹
          </button>
          <div className="route-selector-nav-counter">
            {currentIndex + 1} av {routes.length}
          </div>
          <button
            className="route-selector-nav-btn"
            onClick={() => onNavigate('next')}
            disabled={currentIndex === routes.length - 1}
            title="Neste rute"
          >
            ›
          </button>
        </div>
      )}
    </div>
  );
}
