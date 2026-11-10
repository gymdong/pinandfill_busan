import { useEffect, useMemo, useRef, useState } from 'react';
import type { Block, Coords, Leg } from '@/types/api';
import { resolveBlockPlace } from '@/api/kakaoSession';

type LatLng = { getLat(): number; getLng(): number };
type MapObject = { setMap(map: unknown | null): void };
type KakaoMaps = {
  load(callback: () => void): void;
  LatLng: new (lat: number, lng: number) => LatLng;
  Map: new (node: HTMLElement, options: { center: LatLng; level: number }) => {
    setCenter(center: LatLng): void;
    setBounds(bounds: unknown): void;
  };
  LatLngBounds: new () => { extend(point: LatLng): void };
  Marker: new (options: { map: unknown; position: LatLng; title: string }) => MapObject;
  Polyline: new (options: { map: unknown; path: LatLng[]; strokeWeight: number; strokeColor: string }) => MapObject;
  event: {
    addListener(target: unknown, event: string, handler: (point: { latLng: LatLng }) => void): void;
    removeListener(target: unknown, event: string, handler: (point: { latLng: LatLng }) => void): void;
  };
};

declare global {
  interface Window { kakao?: { maps: KakaoMaps } }
}

let loading: Promise<KakaoMaps> | null = null;

/** 지도 JS 키는 도메인 제한된 브라우저 키만 사용한다. 서버 키를 전달하지 않는다. */
function loadMap(): Promise<KakaoMaps> {
  const key = import.meta.env.VITE_KAKAO_MAP_JS_KEY;
  if (!key) return Promise.reject(new Error('카카오맵 JS 키가 설정되지 않았어요.'));
  if (window.kakao?.maps) return new Promise((resolve) => window.kakao!.maps.load(() => resolve(window.kakao!.maps)));
  if (loading) return loading;
  loading = new Promise<KakaoMaps>((resolve, reject) => {
    const ready = () => {
      if (!window.kakao?.maps) { reject(new Error('카카오맵 SDK가 준비되지 않았어요.')); return; }
      window.kakao.maps.load(() => resolve(window.kakao!.maps));
    };
    const script = document.createElement('script');
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`;
    script.async = true;
    script.onload = ready;
    script.onerror = () => reject(new Error('카카오맵을 불러오지 못했어요.'));
    document.head.appendChild(script);
  }).catch((error: unknown) => { loading = null; throw error; });
  return loading;
}

export interface KakaoMapProps {
  blocks: Block[];
  legs: Leg[];
  selectedId: string | null;
  onSelect(id: string): void;
  onLongPress(coords: Coords): void;
}

export function KakaoMap({ blocks, legs, selectedId, onSelect, onLongPress }: KakaoMapProps) {
  const node = useRef<HTMLDivElement>(null);
  const mapRef = useRef<InstanceType<KakaoMaps['Map']> | null>(null);
  const mapsRef = useRef<KakaoMaps | null>(null);
  const [error, setError] = useState<string | null>(null);
  const points = useMemo(() => blocks.map((block) => ({ block, place: resolveBlockPlace(block.place) })), [blocks]);
  const selectionRef = useRef({ selectedId, points });

  useEffect(() => {
    selectionRef.current = { selectedId, points };
    const selected = points.find(({ block }) => block.id === selectedId)?.place;
    if (selected && mapRef.current && mapsRef.current) {
      mapRef.current.setCenter(new mapsRef.current.LatLng(selected.coords.lat, selected.coords.lng));
    }
  }, [points, selectedId]);

  useEffect(() => {
    let cancelled = false;
    let overlays: MapObject[] = [];
    let cleanup: (() => void) | undefined;
    void loadMap().then((maps) => {
      if (cancelled || !node.current) return;
      const center = points.find(({ place }) => place)?.place?.coords ?? { lat: 35.1796, lng: 129.0756 };
      const map = new maps.Map(node.current, { center: new maps.LatLng(center.lat, center.lng), level: 6 });
      mapRef.current = map; mapsRef.current = maps;
      const bounds = new maps.LatLngBounds();
      const locations = new Map<string, LatLng>();
      for (const { block, place } of points) {
        if (!place) continue;
        const { lat, lng } = place.coords;
        const coord = new maps.LatLng(lat, lng);
        bounds.extend(coord);
        locations.set(block.id, coord);
      }
      if (locations.size > 1) map.setBounds(bounds);
      overlays = points.filter((item) => item.place).map(({ block, place }) => {
        const marker = new maps.Marker({ map, position: locations.get(block.id)!, title: place!.name });
        maps.event.addListener(marker, 'click', () => onSelect(block.id));
        return marker;
      });
      for (let index = 1; index < points.length; index++) {
        const from = points[index - 1]!, to = points[index]!;
        if (!legs.some((leg) => leg.fromBlockId === from.block.id && leg.toBlockId === to.block.id)) continue;
        const start = locations.get(from.block.id), end = locations.get(to.block.id);
        if (start && end) overlays.push(new maps.Polyline({ map, path: [start, end], strokeWeight: 4, strokeColor: '#0e599c' }));
      }
      // SDK가 늦게 로드되어도 마지막으로 선택한 블록에 중심을 맞춘다.
      const latest = selectionRef.current;
      const selected = latest.points.find(({ block }) => block.id === latest.selectedId)?.place;
      if (selected) map.setCenter(new maps.LatLng(selected.coords.lat, selected.coords.lng));

      // SDK 지도 이벤트의 좌표를 사용한다. 이동 중에는 길게 누르기를 취소한다.
      let timer: ReturnType<typeof setTimeout> | undefined;
      const cancel = () => { if (timer) clearTimeout(timer); timer = undefined; };
      const down = (event: { latLng: LatLng }) => {
        cancel();
        timer = setTimeout(() => onLongPress({ lat: event.latLng.getLat(), lng: event.latLng.getLng() }), 650);
      };
      maps.event.addListener(map, 'mousedown', down);
      maps.event.addListener(map, 'mouseup', cancel);
      maps.event.addListener(map, 'dragstart', cancel);
      cleanup = () => {
        cancel();
        maps.event.removeListener(map, 'mousedown', down);
        maps.event.removeListener(map, 'mouseup', cancel);
        maps.event.removeListener(map, 'dragstart', cancel);
      };
    }).catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : '지도를 불러오지 못했어요.'); });
    return () => { cancelled = true; cleanup?.(); overlays.forEach((overlay) => overlay.setMap(null)); mapRef.current = null; mapsRef.current = null; };
  }, [points, legs, onSelect, onLongPress]);

  return <div><div ref={node} role="img" aria-label="일정 경로 지도" style={{ height: 300, background: '#e8f1f8', borderRadius: 12 }} />{error ? <p role="status">{error} 아래 목록에서 장소를 선택할 수 있어요.</p> : null}</div>;
}
