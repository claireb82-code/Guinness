import React, { useEffect, useRef, useState } from 'react';
import { createMarkerSvgDataUrl } from './PintIcon.jsx';
import { markerSize } from '../layout.js';

const GUINNESS_GOOGLE_MAP_STYLES = [
  { elementType: 'geometry', stylers: [{ color: '#171310' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#171310' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#b8ab99' }] },
  {
    featureType: 'administrative.locality',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#c8a45d' }],
  },
  {
    featureType: 'poi',
    elementType: 'labels.text.fill',
    stylers: [{ color: '#8f7e68' }],
  },
  {
    featureType: 'road',
    elementType: 'geometry',
    stylers: [{ color: '#2b241d' }],
  },
  {
    featureType: 'road.highway',
    elementType: 'geometry',
    stylers: [{ color: '#3f3327' }],
  },
  {
    featureType: 'water',
    elementType: 'geometry',
    stylers: [{ color: '#0a0807' }],
  },
];

export function MapCanvas({
  center,
  zoom = 14,
  venues,
  selectedVenue,
  onSelectVenue,
  googleApiKey,
  userLocation = null,
  radiusKm = null,
  onMapClickForNewVenue,
}) {
  const mapContainerRef = useRef(null);
  const leafletMapRef = useRef(null);
  const leafletMarkersRef = useRef([]);
  const nearLayersRef = useRef([]);
  const googleMapRef = useRef(null);
  const googleMarkersRef = useRef([]);
  const [googleSdkReady, setGoogleSdkReady] = useState(false);
  const [googleSdkError, setGoogleSdkError] = useState(null);

  // Dynamically load Google Maps JS SDK when an API key is provided
  useEffect(() => {
    if (!googleApiKey) {
      setGoogleSdkReady(false);
      return;
    }

    if (window.google && window.google.maps) {
      setGoogleSdkReady(true);
      return;
    }

    const existingScript = document.getElementById('google-maps-sdk-script');
    if (existingScript) {
      existingScript.remove();
    }

    const script = document.createElement('script');
    script.id = 'google-maps-sdk-script';
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(googleApiKey)}&libraries=places,marker&v=weekly`;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      setGoogleSdkError(null);
      setGoogleSdkReady(true);
    };
    script.onerror = () => {
      setGoogleSdkError('Could not load Google Maps JS SDK — falling back to interactive dark map.');
      setGoogleSdkReady(false);
    };
    document.head.appendChild(script);
  }, [googleApiKey]);

  // Initialize or update Google Maps when SDK is active
  useEffect(() => {
    if (!googleApiKey || !googleSdkReady || !window.google?.maps || !mapContainerRef.current) {
      return;
    }

    // Clean up Leaflet if switching to Google Maps
    if (leafletMapRef.current) {
      leafletMapRef.current.remove();
      leafletMapRef.current = null;
    }

    if (!googleMapRef.current) {
      googleMapRef.current = new window.google.maps.Map(mapContainerRef.current, {
        center: { lat: center.lat, lng: center.lng },
        zoom,
        mapId: 'DEMO_MAP_ID',
        internalUsageAttributionIds: ['gmp_git_agentskills_v1'],
        disableDefaultUI: false,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
      });

      googleMapRef.current.addListener('click', (e) => {
        if (onMapClickForNewVenue && e.latLng) {
          onMapClickForNewVenue({
            lat: Number(e.latLng.lat().toFixed(5)),
            lng: Number(e.latLng.lng().toFixed(5)),
          });
        }
      });
    } else {
      googleMapRef.current.panTo({ lat: center.lat, lng: center.lng });
      googleMapRef.current.setZoom(zoom);
    }
  }, [googleApiKey, googleSdkReady, center.lat, center.lng, zoom]);

  // Render Google Map Markers using AdvancedMarkerElement
  useEffect(() => {
    if (!googleMapRef.current || !googleSdkReady || !window.google?.maps) return;

    googleMarkersRef.current.forEach((m) => {
      m.map = null;
    });
    googleMarkersRef.current = [];

    const AdvancedMarkerElement = window.google.maps.marker?.AdvancedMarkerElement;
    if (!AdvancedMarkerElement) return;

    venues.forEach((venue) => {
      if (typeof venue.lat !== 'number' || typeof venue.lng !== 'number') return;
      const isSelected = selectedVenue?.id === venue.id;
      const status = venue.guinnessSummary?.status || 'unverified';
      const iconUrl = createMarkerSvgDataUrl(status, isSelected);
      const size = markerSize(isSelected);

      const imgEl = document.createElement('img');
      imgEl.src = iconUrl;
      imgEl.width = size;
      imgEl.height = size;
      imgEl.style.cursor = 'pointer';
      imgEl.alt = `${venue.name} (${venue.guinnessSummary?.statusLabel})`;

      const marker = new AdvancedMarkerElement({
        position: { lat: venue.lat, lng: venue.lng },
        map: googleMapRef.current,
        title: `${venue.name} (${venue.guinnessSummary?.statusLabel})`,
        zIndex: isSelected ? 999 : 10,
      });
      marker.append(imgEl);

      marker.addEventListener('click', () => {
        onSelectVenue(venue);
      });

      googleMarkersRef.current.push(marker);
    });
  }, [venues, selectedVenue, googleSdkReady]);

  // Initialize or update Leaflet Map when in Demo / Keyless mode
  useEffect(() => {
    if (googleApiKey && googleSdkReady) return;
    if (!mapContainerRef.current || !window.L) return;

    if (!leafletMapRef.current) {
      const map = window.L.map(mapContainerRef.current, {
        center: [center.lat, center.lng],
        zoom,
        zoomControl: true,
      });

      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(map);

      map.on('click', (e) => {
        if (onMapClickForNewVenue && e.latlng) {
          onMapClickForNewVenue({
            lat: Number(e.latlng.lat.toFixed(5)),
            lng: Number(e.latlng.lng.toFixed(5)),
          });
        }
      });

      leafletMapRef.current = map;
    } else if (!(userLocation && radiusKm)) {
      // (With Near me on, the map frames the visitor's radius instead; see the effect below.)
      leafletMapRef.current.flyTo([center.lat, center.lng], zoom, {
        duration: 0.85,
      });
    }
  }, [center.lat, center.lng, zoom, googleApiKey, googleSdkReady]);

  // Render Leaflet Markers
  useEffect(() => {
    if (googleApiKey && googleSdkReady) return;
    const map = leafletMapRef.current;
    if (!map || !window.L) return;

    leafletMarkersRef.current.forEach((m) => m.remove());
    leafletMarkersRef.current = [];

    venues.forEach((venue) => {
      if (typeof venue.lat !== 'number' || typeof venue.lng !== 'number') return;
      const isSelected = selectedVenue?.id === venue.id;
      const status = venue.guinnessSummary?.status || 'unverified';
      const iconUrl = createMarkerSvgDataUrl(status, isSelected);
      const size = markerSize(isSelected);

      const customIcon = window.L.icon({
        iconUrl,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        popupAnchor: [0, -size / 2],
        className: 'custom-pint-marker',
      });

      const marker = window.L.marker([venue.lat, venue.lng], {
        icon: customIcon,
        zIndexOffset: isSelected ? 900 : 0,
      }).addTo(map);

      marker.on('click', () => {
        onSelectVenue(venue);
      });

      leafletMarkersRef.current.push(marker);
    });
  }, [venues, selectedVenue, googleApiKey, googleSdkReady]);

  // Near me: the visitor's position and the chosen radius, framed on the map (OpenStreetMap map only).
  useEffect(() => {
    if (googleApiKey && googleSdkReady) return;
    const map = leafletMapRef.current;
    if (!map || !window.L) return;

    nearLayersRef.current.forEach((layer) => layer.remove());
    nearLayersRef.current = [];
    if (!userLocation || !radiusKm) return;

    const circle = window.L.circle([userLocation.lat, userLocation.lng], {
      radius: radiusKm * 1000,
      color: '#4aa3ff',
      weight: 2,
      fillColor: '#4aa3ff',
      fillOpacity: 0.07,
      interactive: false,
      className: 'near-me-circle',
    }).addTo(map);
    const dot = window.L.marker([userLocation.lat, userLocation.lng], {
      icon: window.L.divIcon({ className: 'user-location-marker', html: '<span></span>', iconSize: [20, 20], iconAnchor: [10, 10] }),
      interactive: false,
      keyboard: false,
      zIndexOffset: 1000,
    }).addTo(map);
    nearLayersRef.current = [circle, dot];
    map.fitBounds(circle.getBounds(), { padding: [24, 24], maxZoom: 17 });
  }, [userLocation?.lat, userLocation?.lng, radiusKm, googleApiKey, googleSdkReady]);

  // Pan to selected venue smoothly
  useEffect(() => {
    if (!selectedVenue) return;
    if (googleMapRef.current && googleSdkReady) {
      googleMapRef.current.panTo({ lat: selectedVenue.lat, lng: selectedVenue.lng });
    } else if (leafletMapRef.current) {
      leafletMapRef.current.flyTo([selectedVenue.lat, selectedVenue.lng], Math.max(zoom, 15), {
        duration: 0.65,
      });
    }
  }, [selectedVenue?.id]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <div ref={mapContainerRef} style={{ width: '100%', height: '100%' }} />

      {googleSdkError && (
        <div
          style={{
            position: 'absolute',
            top: '0.75rem',
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(23, 19, 16, 0.94)',
            border: '1px solid #f87171',
            color: '#fca5a5',
            padding: '0.45rem 0.85rem',
            borderRadius: '0.5rem',
            fontSize: '0.76rem',
            zIndex: 500,
          }}
        >
          {googleSdkError}
        </div>
      )}

      {/* Floating Legend */}
      <div
        className="map-legend"
        style={{
          position: 'absolute',
          bottom: '1.25rem',
          left: '1rem',
          background: 'rgba(19, 16, 13, 0.92)',
          border: '1px solid #332a21',
          borderRadius: '0.65rem',
          padding: '0.65rem 0.85rem',
          zIndex: 400,
          backdropFilter: 'blur(6px)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.35rem',
          fontSize: '0.73rem',
          boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
        }}
      >
        <div
          style={{
            fontWeight: 700,
            color: '#c8a45d',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            fontSize: '0.66rem',
            marginBottom: '0.1rem',
          }}
        >
          Guinness Map Key
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: '#34d399',
              display: 'inline-block',
            }}
          />
          <span>Confirmed Draught On Tap</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: '#c8a45d',
              display: 'inline-block',
            }}
          />
          <span>Confirmed Bottles / Cans</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: '#fbbf24',
              display: 'inline-block',
            }}
          />
          <span>Mentioned in Google Reviews</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: '#f87171',
              display: 'inline-block',
            }}
          />
          <span>Confirmed No Guinness</span>
        </div>
      </div>
    </div>
  );
}
