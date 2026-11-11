import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { schedule } from '@/api/mock/fixtures/schedule';
import { KakaoMap } from '@/map/KakaoMap';

describe('카카오맵 SDK 래퍼', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    Reflect.deleteProperty(window, 'kakao');
    document.querySelectorAll('script[src*="dapi.kakao.com/v2/maps/sdk.js"]').forEach((script) => script.remove());
  });

  it('빈 지도도 부산 중심으로 초기화하고 길게 누른 좌표를 전달한다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_JS_KEY', 'test-key');
    const mapConstructor = vi.fn();
    class LatLng {
      constructor(public lat: number, public lng: number) {}
      getLat() { return this.lat; }
      getLng() { return this.lng; }
    }
    const handlers = new Map<string, (event: { latLng: LatLng }) => void>();
    class Point { constructor(public x: number, public y: number) {} }
    // 컨테이너 좌표 (x, y)를 (35 + y/1000, 129 + x/1000)으로 바꾸는 가짜 투영
    const coordsFromContainerPoint = vi.fn((point: Point) => new LatLng(35 + point.y / 1000, 129 + point.x / 1000));
    class MapView {
      constructor(_node: HTMLElement, options: { center: LatLng }) { mapConstructor(options.center); }
      setCenter() {}
      setBounds() {}
      getProjection() { return { coordsFromContainerPoint }; }
    }
    Object.defineProperty(window, 'kakao', { configurable: true, value: { maps: {
      load: (callback: () => void) => callback(), LatLng, Map: MapView, Point,
      LatLngBounds: class { extend() {} }, Marker: class { setMap() {} },
      Polyline: class { setMap() {} },
      event: {
        addListener: (_target: unknown, event: string, handler: (event: { latLng: LatLng }) => void) => handlers.set(event, handler),
        removeListener: (_target: unknown, event: string) => handlers.delete(event),
      },
    } } });
    const onLongPress = vi.fn();
    render(<KakaoMap blocks={[]} legs={[]} selectedId={null} onSelect={vi.fn()} onLongPress={onLongPress} />);
    const container = await screen.findByRole('img', { name: '일정 경로 지도' });
    await act(async () => { await Promise.resolve(); });
    expect(mapConstructor).toHaveBeenCalledWith(expect.objectContaining({ lat: 35.1796, lng: 129.0756 }));
    // jsdom의 getBoundingClientRect는 0을 돌려주므로 clientX/Y가 곧 컨테이너 좌표다.
    const hold = async (events: () => void) => {
      await act(async () => { events(); await new Promise((resolve) => setTimeout(resolve, 700)); });
    };

    // 터치로 길게 누르면 누른 지점의 컨테이너 좌표를 지도 좌표로 바꿔 전달한다.
    await hold(() => fireEvent.pointerDown(container, { clientX: 100, clientY: 50, pointerType: 'touch', isPrimary: true }));
    expect(coordsFromContainerPoint).toHaveBeenLastCalledWith(expect.objectContaining({ x: 100, y: 50 }));
    expect(onLongPress).toHaveBeenCalledWith({ lat: 35.05, lng: 129.1 });

    // 손을 일찍 떼거나, 크게 움직이거나, 지도를 끌면 취소한다.
    await hold(() => { fireEvent.pointerDown(container, { clientX: 10, clientY: 10, isPrimary: true }); fireEvent.pointerUp(container); });
    await hold(() => { fireEvent.pointerDown(container, { clientX: 10, clientY: 10, isPrimary: true }); fireEvent.pointerMove(container, { clientX: 40, clientY: 10 }); });
    await hold(() => { fireEvent.pointerDown(container, { clientX: 10, clientY: 10, isPrimary: true }); handlers.get('dragstart')?.({ latLng: new LatLng(35, 129) }); });
    // 마우스 오른쪽 버튼과 두 번째 손가락은 길게 누르기로 보지 않는다.
    await hold(() => fireEvent.pointerDown(container, { clientX: 10, clientY: 10, pointerType: 'touch', isPrimary: false }));
    await hold(() => fireEvent.pointerDown(container, { clientX: 10, clientY: 10, pointerType: 'mouse', button: 2, isPrimary: true }));
    expect(onLongPress).toHaveBeenCalledTimes(1);

    // 작은 떨림은 허용한다.
    await hold(() => { fireEvent.pointerDown(container, { clientX: 10, clientY: 10, isPrimary: true }); fireEvent.pointerMove(container, { clientX: 13, clientY: 12 }); });
    expect(onLongPress).toHaveBeenCalledTimes(2);
  });

  it('좌표 없는 장소나 구간 없는 장소 사이에는 선을 잇지 않는다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_JS_KEY', 'test-key');
    const polyline = vi.fn();
    class LatLng { constructor(public lat: number, public lng: number) {} getLat() { return this.lat; } getLng() { return this.lng; } }
    Object.defineProperty(window, 'kakao', { configurable: true, value: { maps: {
      load: (callback: () => void) => callback(), LatLng,
      Map: class { setCenter() {} setBounds() {} },
      LatLngBounds: class { extend() {} }, Marker: class { setMap() {} },
      Polyline: class { constructor(options: unknown) { polyline(options); } setMap() {} },
      event: { addListener() {}, removeListener() {} },
    } } });
    const blocks = schedule.days[0]!.blocks;
    render(<KakaoMap blocks={blocks} legs={[]} selectedId={null} onSelect={vi.fn()} onLongPress={vi.fn()} />);
    await act(async () => { await Promise.resolve(); });
    expect(polyline).not.toHaveBeenCalled();
  });

  it('좌표와 구간이 모두 있는 인접 장소만 개략선으로 잇는다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_JS_KEY', 'test-key');
    const polyline = vi.fn();
    class LatLng { constructor(public lat: number, public lng: number) {} getLat() { return this.lat; } getLng() { return this.lng; } }
    Object.defineProperty(window, 'kakao', { configurable: true, value: { maps: {
      load: (callback: () => void) => callback(), LatLng,
      Map: class { setCenter() {} setBounds() {} },
      LatLngBounds: class { extend() {} }, Marker: class { setMap() {} },
      Polyline: class { constructor(options: unknown) { polyline(options); } setMap() {} },
      event: { addListener() {}, removeListener() {} },
    } } });
    const day = schedule.days[0]!;
    render(<KakaoMap blocks={day.blocks} legs={day.legs} selectedId={null} onSelect={vi.fn()} onLongPress={vi.fn()} />);
    await act(async () => { await Promise.resolve(); });
    // 네 블록 중 마지막 카카오 장소는 좌표가 없어 세 번째 구간은 그리지 않는다.
    expect(polyline).toHaveBeenCalledTimes(2);
  });

  it('SDK가 늦게 준비되어도 마지막 선택 장소를 중심으로 이동한다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_JS_KEY', 'test-key');
    let ready!: () => void;
    const setCenter = vi.fn();
    const mapConstructor = vi.fn();
    class LatLng { constructor(public lat: number, public lng: number) {} getLat() { return this.lat; } getLng() { return this.lng; } }
    Object.defineProperty(window, 'kakao', { configurable: true, value: { maps: {
      load: (callback: () => void) => { ready = callback; }, LatLng,
      Map: class { constructor() { mapConstructor(); } setCenter = setCenter; setBounds() {} },
      LatLngBounds: class { extend() {} }, Marker: class { setMap() {} },
      Polyline: class { setMap() {} },
      event: { addListener() {}, removeListener() {} },
    } } });
    const day = schedule.days[0]!;
    const props = { blocks: day.blocks, legs: day.legs, onSelect: vi.fn(), onLongPress: vi.fn() };
    const view = render(<KakaoMap {...props} selectedId={null} />);
    view.rerender(<KakaoMap {...props} selectedId={day.blocks[1]!.id} />);
    await act(async () => { ready(); await Promise.resolve(); });
    expect(mapConstructor).toHaveBeenCalledTimes(1);
    expect(setCenter).toHaveBeenCalledWith(expect.objectContaining({ lat: day.blocks[1]!.place.source === 'PUBLIC' ? day.blocks[1]!.place.lat : 0 }));
  });

  it('스크립트 onload 후에도 SDK 전역이 없으면 오류를 표시한다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_JS_KEY', 'test-key');
    render(<KakaoMap blocks={[]} legs={[]} selectedId={null} onSelect={vi.fn()} onLongPress={vi.fn()} />);
    const script = document.querySelector('script[src*="dapi.kakao.com/v2/maps/sdk.js"]');
    expect(script).not.toBeNull();
    await act(async () => { script!.dispatchEvent(new Event('load')); await Promise.resolve(); });
    expect(await screen.findByText(/카카오맵 SDK가 준비되지 않았어요/)).toBeInTheDocument();
  });
});
