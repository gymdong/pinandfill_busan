import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { placesApi, tripsApi } from '@/api';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import { searchItems } from '@/api/mock/fixtures/places';
import TimelinePage from '@/pages/timeline';

afterEach(() => vi.restoreAllMocks());

describe('코스 타임라인', () => {
  const empty = { ...schedule, days: [] };
  it('고정 시작 시각 없이 고정 상태를 켜는 동작을 제공하지 않는다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getByRole('button', { name: /감천/ }));
    expect(screen.queryByRole('button', { name: '고정' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '고정 해제' })).not.toBeInTheDocument();
  });

  it('이번 접속에서 고르지 않은 카카오 장소는 카카오맵 링크를 새 창으로 제공한다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    // mock 키 형식이 바뀌어도 깨지지 않도록 일정의 카카오 블록에서 기대값을 읽는다.
    const [kakaoPlaceUrl] = schedule.days
      .flatMap((day) => day.blocks)
      .flatMap((block) => (block.place.source === 'KAKAO' ? [block.place.placeUrl] : []));
    const link = await screen.findByRole('link', { name: '카카오맵에서 장소 확인 (새 창)' });
    expect(link).toHaveAttribute('href', kakaoPlaceUrl);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getAllByRole('link', { name: '카카오맵에서 장소 확인 (새 창)' })).toHaveLength(1);
  });

  it('인접한 블록 사이에 검색한 경유지를 삽입 요청한다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [searchItems[0]!] });
    const add = vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getAllByRole('button', { name: '이 구간에 경유지 추가' })[0]!);
    const slot = screen.getByRole('region', { name: '경유지 추가' });
    await userEvent.type(within(slot).getByLabelText('장소 검색'), '민락');
    await userEvent.click(within(slot).getByRole('button', { name: '검색' }));
    await userEvent.click(await within(slot).findByRole('button', { name: '추가' }));
    expect(add).toHaveBeenCalledWith('t1', {
      place: { placeId: searchItems[0]!.placeId }, isFixed: false, origin: 'USER',
      fromBlockId: schedule.days[0]!.blocks[0]!.id, toBlockId: schedule.days[0]!.blocks[1]!.id,
    });
  });
  it('일정과 편집 응답에 같은 경고가 있으면 한 번만 표시한다', async () => {
    const warning = { type: 'HOURS', cause: '영업시간 경고' };
    const warned = { ...schedule, violations: [warning] };
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    vi.spyOn(tripsApi, 'updateBlock').mockResolvedValue({ schedule: warned, violations: [warning] });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getByRole('button', { name: /감천/ }));
    await userEvent.click(screen.getByRole('button', { name: '체류시간 변경' }));
    expect(await screen.findAllByText('영업시간 경고')).toHaveLength(1);
  });
  function renderNavigable() {
    render(<MemoryRouter initialEntries={['/trips/t1']}>
      <Link to="/trips/t2">다른 여행</Link>
      <Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes>
    </MemoryRouter>);
  }

  it('편집 후 다른 여행으로 이동하면 이전 여행의 편집 일정과 경고를 표시하지 않는다', async () => {
    vi.spyOn(tripsApi, 'get').mockImplementation(async (id) => ({ trip, schedule: id === 't2' ? empty : schedule }));
    vi.spyOn(tripsApi, 'updateBlock').mockResolvedValue({ schedule, violations: [{ type: 'HOURS', cause: '상위 경고' }] });
    renderNavigable();
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getByRole('button', { name: /감천/ }));
    await userEvent.click(screen.getByRole('button', { name: '체류시간 변경' }));
    expect(await screen.findByText('상위 경고')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: '다른 여행' }));
    expect(await screen.findByText('표시할 일정이 없습니다.')).toBeInTheDocument();
    expect(screen.queryByText('상위 경고')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '직전 편집 되돌리기' })).toBeDisabled();
  });

  it('편집 요청이 진행 중일 때 이동해도 늦은 응답이 새 여행에 섞이지 않는다', async () => {
    vi.spyOn(tripsApi, 'get').mockImplementation(async (id) => ({ trip, schedule: id === 't2' ? empty : schedule }));
    let resolve!: (result: { schedule: typeof schedule; violations: [] }) => void;
    vi.spyOn(tripsApi, 'updateBlock').mockReturnValue(new Promise((done) => { resolve = done; }));
    renderNavigable();
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getByRole('button', { name: /감천/ }));
    await userEvent.click(screen.getByRole('button', { name: '체류시간 변경' }));
    await userEvent.click(screen.getByRole('link', { name: '다른 여행' }));
    await screen.findByText('표시할 일정이 없습니다.');
    resolve({ schedule, violations: [] });
    await waitFor(() => expect(screen.queryByRole('button', { name: /감천/ })).not.toBeInTheDocument());
  });

  it('차량 구간을 도보로 잘못 표시하지 않는다', async () => {
    const carSchedule = { ...schedule, days: [{ ...schedule.days[0]!, legs: [{ ...schedule.days[0]!.legs[0]!, mode: 'CAR' as const }] }] };
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule: carSchedule });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText(/자동차 · 25분/)).toBeInTheDocument();
  });
  it('장소 이름으로 검색하고 선택한 장소를 블록으로 추가한다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [searchItems[0]!] });
    const add = vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.type(screen.getByLabelText('장소 검색'), '민락');
    await userEvent.click(screen.getByRole('button', { name: '검색' }));
    await userEvent.click(await screen.findByRole('button', { name: '추가' }));
    expect(placesApi.search).toHaveBeenCalledWith({ q: '민락' });
    expect(add).toHaveBeenCalledWith('t1', { place: { placeId: searchItems[0]!.placeId }, isFixed: false, origin: 'USER', dayNo: 1 });
  });
  it('서버 일정을 보여 주고 편집 응답의 새 일정을 반영한다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    const changed = {
      ...schedule,
      days: [{ ...schedule.days[0]!, blocks: schedule.days[0]!.blocks.map((block, i) => i === 0 ? { ...block, stayMin: 120 } : block) }],
    };
    vi.spyOn(tripsApi, 'updateBlock').mockResolvedValue({ schedule: changed, violations: [] });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText('코스 타임라인')).toBeInTheDocument();
    expect(screen.getByText(/이동시간 확인 필요/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /감천/ }));
    await userEvent.clear(screen.getByLabelText('체류시간(분)'));
    await userEvent.type(screen.getByLabelText('체류시간(분)'), '120');
    await userEvent.click(screen.getByRole('button', { name: '체류시간 변경' }));
    expect(await screen.findByText(/체류 120분/)).toBeInTheDocument();
    expect(tripsApi.updateBlock).toHaveBeenCalledWith('t1', schedule.days[0]!.blocks[0]!.id, { stayMin: 120 });
  });
});
