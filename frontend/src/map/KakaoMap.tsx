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
    setBounds(bounds: unknown, paddingTop?: number, paddingRight?: number, paddingBottom?: number, paddingLeft?: number): void;
    panBy(dx: number, dy: number): void;
    getProjection(): { coordsFromContainerPoint(point: unknown): LatLng };
  };
  Point: new (x: number, y: number) => unknown;
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

const LONG_PRESS_MS = 650;
/** 손가락 떨림은 허용하고 지도를 끄는 동작은 길게 누르기로 보지 않는다. */
const MOVE_TOLERANCE_PX = 8;

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
  /** 지도 영역 크기·모양. 지정하지 않으면 높이 300px 카드로 그린다. */
  className?: string;
  /**
   * 지도 위를 덮는 UI(위 버튼 줄·아래 시트)의 높이(px). 마커가 그 밑에 숨지 않게 범위 맞춤과 선택 중심에 반영한다.
   * 그릴 때마다 다시 재므로 함수로 받는다.
   */
  getCovered?: () => { top: number; bottom: number };
}

const NO_COVER = () => ({ top: 0, bottom: 0 });
const EDGE_PX = 24;

export function KakaoMap({ blocks, legs, selectedId, onSelect, onLongPress, className, getCovered = NO_COVER }: KakaoMapProps) {
  const node = useRef<HTMLDivElement>(null);
  const mapRef = useRef<InstanceType<KakaoMaps['Map']> | null>(null);
  const mapsRef = useRef<KakaoMaps | null>(null);
  const [error, setError] = useState<string | null>(null);
  const points = useMemo(() => blocks.map((block) => ({ block, place: resolveBlockPlace(block.place) })), [blocks]);
  const selectionRef = useRef({ selectedId, points });
  const coveredRef = useRef(getCovered);
  useEffect(() => { coveredRef.current = getCovered; }, [getCovered]);
  /** 덮인 영역을 뺀 보이는 부분의 가운데에 좌표를 둔다(시트가 아래 절반을 가려도 마커가 보이게). */
  const centerVisible = (map: InstanceType<KakaoMaps['Map']>, maps: KakaoMaps, coords: Coords) => {
    map.setCenter(new maps.LatLng(coords.lat, coords.lng));
    const { top, bottom } = coveredRef.current();
    if (bottom !== top) map.panBy(0, Math.round((bottom - top) / 2));
  };

  useEffect(() => {
    selectionRef.current = { selectedId, points };
    const selected = points.find(({ block }) => block.id === selectedId)?.place;
    if (selected && mapRef.current && mapsRef.current) centerVisible(mapRef.current, mapsRef.current, selected.coords);
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
      if (locations.size > 1) {
        const { top, bottom } = coveredRef.current();
        map.setBounds(bounds, top + EDGE_PX, EDGE_PX, bottom + EDGE_PX, EDGE_PX);
      }
      overlays = points.filter((item) => item.place).map(({ block, place }) => {
        const marker = new maps.Marker({ map, position: locations.get(block.id)!, title: place!.name });
        maps.event.addListener(marker, 'click', () => onSelect(block.id));
        return marker;
      });
      // SDK 는 CSS 변수를 읽지 못하므로 토큰 값을 꺼내 넘긴다.
      const lineColor = getComputedStyle(document.documentElement).getPropertyValue('--color-ink').trim() || '#14202c';
      for (let index = 1; index < points.length; index++) {
        const from = points[index - 1]!, to = points[index]!;
        if (!legs.some((leg) => leg.fromBlockId === from.block.id && leg.toBlockId === to.block.id)) continue;
        const start = locations.get(from.block.id), end = locations.get(to.block.id);
        if (start && end) overlays.push(new maps.Polyline({ map, path: [start, end], strokeWeight: 4, strokeColor: lineColor }));
      }
      // SDK가 늦게 로드되어도 마지막으로 선택한 블록에 중심을 맞춘다.
      const latest = selectionRef.current;
      const selected = latest.points.find(({ block }) => block.id === latest.selectedId)?.place;
      if (selected) centerVisible(map, maps, selected.coords);

      // 카카오 Map 이벤트에는 mousedown/mouseup이 없으므로 컨테이너 DOM의 pointer 이벤트로
      // 마우스·터치 길게 누르기를 감지하고, 컨테이너 좌표를 지도 좌표로 변환한다.
      const container = node.current;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let start: { x: number; y: number } | null = null;
      const cancel = () => { if (timer) clearTimeout(timer); timer = undefined; start = null; };
      const down = (event: PointerEvent) => {
        cancel();
        if (event.isPrimary === false || (event.pointerType === 'mouse' && event.button !== 0)) return;
        const rect = container.getBoundingClientRect();
        const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        start = { x: event.clientX, y: event.clientY };
        timer = setTimeout(() => {
          timer = undefined; start = null;
          const latLng = map.getProjection().coordsFromContainerPoint(new maps.Point(point.x, point.y));
          onLongPress({ lat: latLng.getLat(), lng: latLng.getLng() });
        }, LONG_PRESS_MS);
      };
      const move = (event: PointerEvent) => {
        if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > MOVE_TOLERANCE_PX) cancel();
      };
      // 길게 누를 때 모바일 브라우저의 기본 메뉴가 뜨지 않게 한다.
      const blockMenu = (event: Event) => event.preventDefault();
      const domEvents: [string, EventListener][] = [
        ['pointerdown', down as EventListener], ['pointermove', move as EventListener],
        ['pointerup', cancel], ['pointercancel', cancel], ['pointerleave', cancel], ['contextmenu', blockMenu],
      ];
      domEvents.forEach(([name, handler]) => container.addEventListener(name, handler));
      maps.event.addListener(map, 'dragstart', cancel);
      cleanup = () => {
        cancel();
        domEvents.forEach(([name, handler]) => container.removeEventListener(name, handler));
        maps.event.removeListener(map, 'dragstart', cancel);
      };
    }).catch((cause: unknown) => { if (!cancelled) setError(cause instanceof Error ? cause.message : '지도를 불러오지 못했어요.'); });
    return () => { cancelled = true; cleanup?.(); overlays.forEach((overlay) => overlay.setMap(null)); mapRef.current = null; mapsRef.current = null; };
  }, [points, legs, onSelect, onLongPress]);

  // 바깥 div 의 크기·위치는 호출한 쪽이 정하고(없으면 높이 300px 카드), 안쪽 div 가 지도와 안내의 기준이 된다.
  return <div className={className} style={className ? undefined : { height: 300, borderRadius: 12, overflow: 'hidden' }}>
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={node} role="img" aria-label="일정 경로 지도" style={{ position: 'absolute', inset: 0, background: 'var(--color-accent-soft)' }} />
      {error ? <p role="status" style={{ position: 'absolute', inset: '35% 24px auto', textAlign: 'center', color: 'var(--color-ink-muted)', fontSize: 'var(--text-s)' }}>{error} 아래 목록에서 장소를 선택할 수 있어요.</p> : null}
    </div>
  </div>;
}
