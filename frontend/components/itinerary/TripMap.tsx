"use client";

import { MapPinned } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getMapsConfig } from "@/lib/api";
import type { ItineraryMapPoint } from "@/lib/itineraryMap";
import type {
  DivIcon,
  Map as LeafletMap,
  Marker as LeafletMarker,
  TileLayer,
} from "leaflet";

export type TripMapStatus = "loading" | "ready" | "unavailable";

type TripMapProps = {
  mapSectionId: string;
  onMarkerSelect: (pointId: string) => void;
  onStatusChange: (status: TripMapStatus) => void;
  points: readonly ItineraryMapPoint[];
  selectedMapPointId: string | null;
};

type MarkerEntry = {
  marker: LeafletMarker;
  point: ItineraryMapPoint;
  select: () => void;
};

type MarkerIconFactory = (sequence: number, selected: boolean) => DivIcon;

export function TripMap({
  mapSectionId,
  onMarkerSelect,
  onStatusChange,
  points,
  selectedMapPointId,
}: TripMapProps) {
  const [shouldLoad, setShouldLoad] = useState(false);
  const [status, setStatus] = useState<TripMapStatus>("loading");
  const sectionRef = useRef<HTMLElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const markersRef = useRef<Map<string, MarkerEntry>>(new Map());
  const markerIconRef = useRef<MarkerIconFactory | null>(null);
  const markerSelectRef = useRef(onMarkerSelect);
  const statusChangeRef = useRef(onStatusChange);
  const selectedPointRef = useRef(selectedMapPointId);

  markerSelectRef.current = onMarkerSelect;
  statusChangeRef.current = onStatusChange;
  selectedPointRef.current = selectedMapPointId;

  useEffect(() => {
    const section = sectionRef.current;
    if (!section || typeof IntersectionObserver === "undefined") {
      setShouldLoad(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShouldLoad(true);
          observer.disconnect();
        }
      },
      { rootMargin: "320px" },
    );
    observer.observe(section);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!shouldLoad) {
      return;
    }

    let cancelled = false;
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const mapCanvas: HTMLDivElement = canvas;
    let tileLayer: TileLayer | null = null;
    let mapLoadTimeout: ReturnType<typeof setTimeout> | null = null;

    const handleTilesLoaded = () => {
      if (!cancelled) {
        clearMapLoadTimeout();
        tileLayer?.off("tileerror", handleTileError);
        updateStatus("ready");
      }
    };
    const handleTileError = () => {
      if (!cancelled) {
        clearMapLoadTimeout();
        tileLayer?.off("load", handleTilesLoaded);
        updateStatus("unavailable");
      }
    };

    async function initializeMap() {
      try {
        const config = await getMapsConfig();
        if (cancelled) {
          return;
        }
        if (!config.enabled || !config.api_key) {
          updateStatus("unavailable");
          return;
        }

        const L = await import("leaflet");
        if (cancelled) {
          return;
        }

        const map = L.map(mapCanvas, {
          attributionControl: true,
          zoomControl: true,
        });
        mapRef.current = map;

        const tilePath = L.Browser.retina
          ? "{z}/{x}/{y}@2x.png"
          : "{z}/{x}/{y}.png";
        tileLayer = L.tileLayer(
          `https://maps.geoapify.com/v1/tile/osm-bright/${tilePath}?apiKey=${encodeURIComponent(
            config.api_key,
          )}`,
          {
            attribution:
              'Powered by <a href="https://www.geoapify.com/" target="_blank">Geoapify</a> | &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
            maxZoom: 20,
          },
        );
        tileLayer.once("load", handleTilesLoaded);
        tileLayer.once("tileerror", handleTileError);
        tileLayer.addTo(map);
        mapLoadTimeout = setTimeout(handleTileError, 12_000);

        const createMarkerIcon: MarkerIconFactory = (sequence, selected) =>
          L.divIcon({
            className: `itineraryMapMarker ${
              selected ? "itineraryMapMarkerSelected" : ""
            }`,
            html: `<span><b>${sequence}</b></span>`,
            iconAnchor: [18, 42],
            iconSize: [36, 42],
          });
        markerIconRef.current = createMarkerIcon;

        points.forEach((point) => {
          const selected = selectedPointRef.current === point.id;
          const marker = L.marker([point.latitude, point.longitude], {
            alt: point.name,
            icon: createMarkerIcon(point.sequence, selected),
            keyboard: true,
            riseOnHover: true,
            title: point.name,
            zIndexOffset: selected ? 10_000 : point.sequence,
          }).addTo(map);
          const select = () => markerSelectRef.current(point.id);
          marker.on("click", select);
          markersRef.current.set(point.id, { marker, point, select });
        });

        const firstPoint = points[0];
        if (points.length === 1) {
          map.setView([firstPoint.latitude, firstPoint.longitude], 14);
        } else {
          const bounds = L.latLngBounds(
            points.map((point) => [point.latitude, point.longitude]),
          );
          map.fitBounds(bounds, { maxZoom: 15, padding: [60, 60] });
        }
        map.whenReady(() => map.invalidateSize());
      } catch {
        if (!cancelled) {
          console.error("Trip map failed to load.");
          updateStatus("unavailable");
        }
      }
    }

    function updateStatus(nextStatus: TripMapStatus) {
      setStatus(nextStatus);
      statusChangeRef.current(nextStatus);
    }

    function clearMapLoadTimeout() {
      if (mapLoadTimeout !== null) {
        clearTimeout(mapLoadTimeout);
        mapLoadTimeout = null;
      }
    }

    void initializeMap();
    return () => {
      cancelled = true;
      clearMapLoadTimeout();
      tileLayer?.off("load", handleTilesLoaded);
      tileLayer?.off("tileerror", handleTileError);
      markersRef.current.forEach(({ marker, select }) => {
        marker.off("click", select);
        marker.remove();
      });
      markersRef.current.clear();
      markerIconRef.current = null;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [points, shouldLoad]);

  useEffect(() => {
    const createMarkerIcon = markerIconRef.current;
    if (createMarkerIcon) {
      markersRef.current.forEach(({ marker, point }, pointId) => {
        const selected = pointId === selectedMapPointId;
        marker.setIcon(createMarkerIcon(point.sequence, selected));
        marker.setZIndexOffset(selected ? 10_000 : point.sequence);
      });
    }

    if (status !== "ready" || selectedMapPointId === null) {
      return;
    }
    const entry = markersRef.current.get(selectedMapPointId);
    const map = mapRef.current;
    if (!entry || !map) {
      return;
    }
    map.panTo([entry.point.latitude, entry.point.longitude]);
    if (map.getZoom() < 14) {
      map.setZoom(14);
    }
  }, [selectedMapPointId, status]);

  const headingId = `${mapSectionId}-heading`;
  return (
    <section
      aria-labelledby={headingId}
      className="tripMapSection"
      id={mapSectionId}
      ref={sectionRef}
    >
      <header className="tripMapHeader">
        <span>
          <MapPinned aria-hidden="true" size={19} />
        </span>
        <div>
          <p>Trip map</p>
          <h3 id={headingId}>
            {points.length}{" "}
            {points.length === 1 ? "planned place" : "planned places"}
          </h3>
        </div>
      </header>
      <div className="tripMapFrame">
        <div className="tripMapCanvas" ref={canvasRef} />
        {status !== "ready" ? (
          <div
            className={`tripMapState ${
              status === "unavailable" ? "tripMapUnavailable" : ""
            }`}
            role="status"
          >
            {status === "unavailable"
              ? "Map unavailable"
              : "Loading trip map..."}
          </div>
        ) : null}
      </div>
    </section>
  );
}
