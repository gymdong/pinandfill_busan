import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import MapViewPage from '@/pages/map-view';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  at: vi.fn(),
  addBlock: vi.fn(),
  remember: vi.fn(),
}));

vi.mock('@/api', () => ({
  tripsApi: { get: mocks.get, addBlock: mocks.addBlock },
  placesApi: { at: mocks.at },
  toApiError: (error: Error) => error,
}));
vi.mock('@/api/kakaoSession', () => ({
  resolveBlockPlace: (place: { source: string; name?: string; lat?: number; lng?: number }) =>
    place.source === 'PUBLIC' ? { name: place.name, coords: { lat: place.lat, lng: place.lng } } : null,
  rememberKakaoPlace: mocks.remember,
}));
vi.mock('@/map/KakaoMap', () => ({
  KakaoMap: ({ onLongPress, onSelect, blocks }: { onLongPress: (coords: { lat: number; lng: number }) => void; onSelect: (id: string) => void; blocks: { id: string }[] }) =>
    <div><button onClick={() => onLongPress({ lat: 35, lng: 129 })}>지도 길게 누르기</button><button onClick={() => onSelect(blocks[0]!.id)}>마커 선택</button></div>,
}));

function renderPage() {
  render(<MemoryRouter initialEntries={['/trips/t1/map']}><Routes><Route path="/trips/:tripId/map" element={<MapViewPage />} /></Routes></MemoryRouter>);
}

function SwitchTrip() {
  const navigate = useNavigate();
  return <button onClick={() => navigate('/trips/t2/map')}>다른 여행</button>;
}

describe('지도 보기', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ trip, schedule });
    mocks.at.mockResolvedValue({ places: [{ kakaoPlaceId: 'k1', placeUrl: 'https://place.map.kakao.com/1', placeId: null, name: '새 장소', coords: { lat: 35, lng: 129 } }], nearbyCount: 1 });
    mocks.addBlock.mockResolvedValue({ schedule, violations: [] });
  });

  it('일차 경로와 이동수단·추정 시간을 표시하고 선택을 동기화한다', async () => {
    renderPage();
    expect(await screen.findByText('1일차 장소 순서')).toBeInTheDocument();
    expect(screen.getByText(/대중교통 · 30분 \(추정\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('마커 선택'));
    expect(screen.getByText(/선택한 장소: 감천/)).toBeInTheDocument();
  });

  it('이번 접속에서 고르지 않은 카카오 장소는 카카오맵 링크를 새 창으로 제공한다', async () => {
    renderPage();
    const link = await screen.findByRole('link', { name: '카카오맵에서 장소 확인 (새 창)' });
    expect(link).toHaveAttribute('href', 'https://example.com/mock-kakao-place/3');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('지도에서 찾은 카카오 장소를 핵심지로 추가한다', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    expect(await screen.findByText('새 장소')).toBeInTheDocument();
    fireEvent.click(screen.getByText('핵심지에 추가'));
    await waitFor(() => expect(mocks.addBlock).toHaveBeenCalledWith('t1', expect.objectContaining({
      place: { kakaoPlaceId: 'k1', placeUrl: 'https://place.map.kakao.com/1' }, isFixed: false, origin: 'USER',
    })));
    expect(mocks.remember).toHaveBeenCalledWith('k1', { name: '새 장소', coords: { lat: 35, lng: 129 } });
  });

  it('서버가 반환한 위반과 충돌을 숨기지 않는다', async () => {
    mocks.addBlock.mockResolvedValue({ schedule: { ...schedule, conflicts: [{ cause: '고정 블록과 충돌', blockIds: [] }] }, violations: [{ type: 'HOURS', cause: '영업시간 위반' }] });
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('핵심지에 추가'));
    expect(await screen.findByText('영업시간 위반')).toBeInTheDocument();
    expect(screen.getByText('고정 블록과 충돌')).toBeInTheDocument();
  });

  it('여행 ID가 바뀌면 이전 여행의 선택과 늦은 추가 응답을 새 여행에 적용하지 않는다', async () => {
    let resolveAdd!: (value: unknown) => void;
    mocks.addBlock.mockImplementation(() => new Promise((resolve) => { resolveAdd = resolve; }));
    render(<MemoryRouter initialEntries={['/trips/t1/map']}><SwitchTrip /><Routes><Route path="/trips/:tripId/map" element={<MapViewPage />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('핵심지에 추가'));
    fireEvent.click(screen.getByText('마커 선택'));
    expect(screen.getByText(/선택한 장소: 감천/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('다른 여행'));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('t2', expect.anything()));
    expect(screen.queryByText(/선택한 장소: 감천/)).not.toBeInTheDocument();
    resolveAdd({ schedule: { ...schedule, violations: [{ type: 'OLD', cause: '이전 여행 경고' }] }, violations: [] });
    await waitFor(() => expect(screen.queryByText('이전 여행 경고')).not.toBeInTheDocument());
  });

  it('빈 일정에서도 지도에서 첫 장소를 찾아 추가할 수 있다', async () => {
    mocks.get.mockResolvedValue({ trip, schedule: { days: [], violations: [], conflicts: [] } });
    renderPage();
    expect(await screen.findByText('아직 장소가 없어요. 지도에서 위치를 길게 눌러 추가하세요.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('핵심지에 추가'));
    await waitFor(() => expect(mocks.addBlock).toHaveBeenCalledWith('t1', expect.objectContaining({ isFixed: false })));
  });

  it('수정 응답과 일정에 같은 위반이 있으면 경고를 한 번만 보여 준다', async () => {
    const warning = { type: 'HOURS', cause: '영업시간 위반' };
    mocks.addBlock.mockResolvedValue({ schedule: { ...schedule, violations: [warning] }, violations: [warning] });
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('핵심지에 추가'));
    await waitFor(() => expect(screen.getAllByText('영업시간 위반')).toHaveLength(1));
  });
});
