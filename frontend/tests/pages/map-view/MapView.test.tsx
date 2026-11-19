import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import { parseErrorResponse } from '@/api/errors';
import MapViewPage from '@/pages/map-view';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  at: vi.fn(),
  addBlock: vi.fn(),
  remember: vi.fn(),
}));

// ApiError·toApiError는 실제 것을 써서 서버 오류 본문 → ApiError.fields → 화면 경로를 그대로 거친다.
vi.mock('@/api', async (importActual) => ({
  ...(await importActual<typeof import('@/api')>()),
  tripsApi: { get: mocks.get, addBlock: mocks.addBlock },
  placesApi: { at: mocks.at },
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

const KAKAO_CANDIDATE = { kakaoPlaceId: 'k1', placeUrl: 'https://place.map.kakao.com/1', placeId: null, name: '새 장소', coords: { lat: 35, lng: 129 } };
const PUBLIC_CANDIDATE = { kakaoPlaceId: 'k2', placeUrl: 'https://place.map.kakao.com/2', placeId: 'p2', name: '공공 장소', coords: { lat: 35, lng: 129 } };

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
    // 기본 후보는 공공 DB에 매칭된 장소다. 체류시간을 고를 필요가 없다.
    mocks.at.mockResolvedValue({ places: [PUBLIC_CANDIDATE], nearbyCount: 1 });
    mocks.addBlock.mockResolvedValue({ schedule, violations: [] });
  });

  it('일차 경로와 이동수단·추정 시간을 표시하고 선택을 동기화한다', async () => {
    renderPage();
    expect(await screen.findByText('1일차 장소 순서')).toBeInTheDocument();
    expect(screen.getByText(/대중교통 · 30분 \(추정\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('마커 선택'));
    expect(within(screen.getByRole('region', { name: '선택한 장소' })).getByRole('heading', { name: /감천/ })).toBeInTheDocument();
  });

  it('이번 접속에서 고르지 않은 카카오 장소는 카카오맵 링크를 새 창으로 제공한다', async () => {
    renderPage();
    // mock 키 형식이 바뀌어도 깨지지 않도록 일정의 카카오 블록에서 기대값을 읽는다.
    const [kakaoPlaceUrl] = schedule.days
      .flatMap((day) => day.blocks)
      .flatMap((block) => (block.place.source === 'KAKAO' ? [block.place.placeUrl] : []));
    const link = await screen.findByRole('link', { name: '카카오맵에서 장소 확인 (새 창)' });
    expect(link).toHaveAttribute('href', kakaoPlaceUrl);
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('지도에서 찾은 카카오 장소는 머무를 시간을 골라야 추가한다(#18 PM 결정 4)', async () => {
    mocks.at.mockResolvedValue({ places: [KAKAO_CANDIDATE], nearbyCount: 1 });
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    expect(await screen.findByText('새 장소')).toBeInTheDocument();
    const stay = screen.getByLabelText('새 장소 머무를 시간');
    // 기본값을 두지 않는다.
    expect(stay).toHaveValue('');
    fireEvent.click(screen.getByText('꼭 갈 곳에 추가'));
    expect(screen.getByRole('alert')).toHaveTextContent('머무를 시간을 골라 주세요.');
    expect(stay).toHaveAttribute('aria-invalid', 'true');
    expect(mocks.addBlock).not.toHaveBeenCalled();

    fireEvent.change(stay, { target: { value: '90' } });
    expect(screen.queryByText('머무를 시간을 골라 주세요.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('꼭 갈 곳에 추가'));
    await waitFor(() => expect(mocks.addBlock).toHaveBeenCalledWith('t1', expect.objectContaining({
      place: { kakaoPlaceId: 'k1', placeUrl: 'https://place.map.kakao.com/1' }, isFixed: false, origin: 'USER', stayMin: 90,
    })));
    expect(mocks.remember).toHaveBeenCalledWith('k1', { name: '새 장소', coords: { lat: 35, lng: 129 } });
  });

  it('공공 DB 장소는 머무를 시간 없이 추가하고 stayMin을 보내지 않는다', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    expect(await screen.findByText('공공 장소')).toBeInTheDocument();
    expect(screen.queryByLabelText('공공 장소 머무를 시간')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('꼭 갈 곳에 추가'));
    await waitFor(() => expect(mocks.addBlock).toHaveBeenCalledTimes(1));
    expect(mocks.addBlock.mock.calls[0]![1]).toEqual({ place: { placeId: 'p2' }, isFixed: false, origin: 'USER', dayNo: 1 });
  });

  it('서버가 체류시간 근거가 없다고 하면(fields.stayMin) 그 후보에 머무를 시간 칸을 띄운다', async () => {
    const message = '체류시간을 정할 수 없는 장소예요. 머무를 시간을 골라 주세요.';
    // 백엔드가 보내는 본문 그대로 ApiError로 바꾼다(backend trips/router.py StayDurationRequiredError).
    mocks.addBlock.mockRejectedValueOnce(parseErrorResponse(400, { error: { id: 'ERR-001', message, fields: { stayMin: message } } }));
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('꼭 갈 곳에 추가'));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    const stay = screen.getByLabelText('공공 장소 머무를 시간');
    fireEvent.change(stay, { target: { value: '60' } });
    fireEvent.click(screen.getByText('꼭 갈 곳에 추가'));
    await waitFor(() => expect(mocks.addBlock).toHaveBeenLastCalledWith('t1', expect.objectContaining({ place: { placeId: 'p2' }, stayMin: 60 })));
  });

  it('2일차로 전환한 뒤 추가하면 보고 있는 일차를 dayNo로 보낸다', async () => {
    const dayTwo = { ...structuredClone(schedule.days[0]!), dayNo: 2, date: '2026-10-18', blocks: [], legs: [], crowd: [] };
    mocks.get.mockResolvedValue({ trip, schedule: { ...schedule, days: [...schedule.days, dayTwo] } });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '2일차' }));
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('꼭 갈 곳에 추가'));
    await waitFor(() => expect(mocks.addBlock).toHaveBeenCalledWith('t1', expect.objectContaining({ dayNo: 2 })));
  });

  it('서버가 반환한 위반과 충돌을 숨기지 않는다', async () => {
    mocks.addBlock.mockResolvedValue({ schedule: { ...schedule, conflicts: [{ cause: '고정 블록과 충돌', blockIds: [] }] }, violations: [{ type: 'HOURS', cause: '영업시간 위반' }] });
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('꼭 갈 곳에 추가'));
    expect(await screen.findByText('영업시간 위반')).toBeInTheDocument();
    expect(screen.getByText('고정 블록과 충돌')).toBeInTheDocument();
  });

  it('여행 ID가 바뀌면 이전 여행의 선택과 늦은 추가 응답을 새 여행에 적용하지 않는다', async () => {
    let resolveAdd!: (value: unknown) => void;
    mocks.addBlock.mockImplementation(() => new Promise((resolve) => { resolveAdd = resolve; }));
    render(<MemoryRouter initialEntries={['/trips/t1/map']}><SwitchTrip /><Routes><Route path="/trips/:tripId/map" element={<MapViewPage />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('꼭 갈 곳에 추가'));
    fireEvent.click(screen.getByText('마커 선택'));
    expect(within(screen.getByRole('region', { name: '선택한 장소' })).getByRole('heading', { name: /감천/ })).toBeInTheDocument();
    fireEvent.click(screen.getByText('다른 여행'));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('t2', expect.anything()));
    expect(screen.queryByRole('region', { name: '선택한 장소' })).not.toBeInTheDocument();
    resolveAdd({ schedule: { ...schedule, violations: [{ type: 'OLD', cause: '이전 여행 경고' }] }, violations: [] });
    await waitFor(() => expect(screen.queryByText('이전 여행 경고')).not.toBeInTheDocument());
  });

  it('빈 일정에서도 지도에서 첫 장소를 찾아 추가할 수 있다', async () => {
    mocks.get.mockResolvedValue({ trip, schedule: { days: [], violations: [], conflicts: [] } });
    renderPage();
    expect(await screen.findByText('아직 장소가 없어요. 지도에서 위치를 길게 눌러 추가하세요.')).toBeInTheDocument();
    fireEvent.click(screen.getByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('꼭 갈 곳에 추가'));
    await waitFor(() => expect(mocks.addBlock).toHaveBeenCalledWith('t1', expect.objectContaining({ isFixed: false })));
  });

  it('수정 응답과 일정에 같은 위반이 있으면 경고를 한 번만 보여 준다', async () => {
    const warning = { type: 'HOURS', cause: '영업시간 위반' };
    mocks.addBlock.mockResolvedValue({ schedule: { ...schedule, violations: [warning] }, violations: [warning] });
    renderPage();
    fireEvent.click(await screen.findByText('지도 길게 누르기'));
    fireEvent.click(await screen.findByText('꼭 갈 곳에 추가'));
    await waitFor(() => expect(screen.getAllByText('영업시간 위반')).toHaveLength(1));
  });
});
