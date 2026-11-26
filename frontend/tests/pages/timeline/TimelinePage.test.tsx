import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { placesApi, tripsApi } from '@/api';
import { parseErrorResponse } from '@/api/errors';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import { placeSummaries, searchItems, waypointCandidates } from '@/api/mock/fixtures/places';
import TimelinePage from '@/pages/timeline';

afterEach(() => vi.restoreAllMocks());

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname + location.search}</p>;
}

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

  it('공공 장소 블록은 그 일차 날짜를 담아 장소 상세로 연결한다(FR-008)', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    const [day] = schedule.days;
    const taejongdae = placeSummaries.taejongdae;
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes>
      <Route path="/trips/:tripId" element={<TimelinePage />} />
      <Route path="/places/:placeId" element={<LocationProbe />} />
    </Routes></MemoryRouter>);

    const link = await screen.findByRole('link', { name: '태종대 장소 상세 보기' });
    expect(link).toHaveAttribute('href', `/places/${taejongdae.id}?date=${day!.date}`);
    // 카카오 장소는 공공 DB 상세가 없어 연결하지 않는다.
    expect(screen.getAllByRole('link', { name: /장소 상세 보기$/ })).toHaveLength(3);
    await userEvent.click(link);
    expect(await screen.findByTestId('location')).toHaveTextContent(`/places/${taejongdae.id}?date=2026-10-17`);
  });

  it('인접한 블록 사이에 검색한 경유지를 삽입 요청한다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [searchItems[0]!] });
    const add = vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getAllByRole('button', { name: '사이에 들를 곳 찾기' })[0]!);
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
    await userEvent.click(screen.getByRole('button', { name: '장소 추가' }));
    await userEvent.type(screen.getByLabelText('장소 검색'), '민락');
    await userEvent.click(screen.getByRole('button', { name: '검색' }));
    await userEvent.click(await screen.findByRole('button', { name: '추가' }));
    expect(placesApi.search).toHaveBeenCalledWith({ q: '민락' });
    expect(add).toHaveBeenCalledWith('t1', { place: { placeId: searchItems[0]!.placeId }, isFixed: false, origin: 'USER', dayNo: 1 });
  });
  it('여러 날 일정에서는 보고 있는 일차의 마지막에 추가한다', async () => {
    const twoDays = { ...schedule, days: [schedule.days[0]!, { ...schedule.days[0]!, dayNo: 2, blocks: [], legs: [] }] };
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule: twoDays });
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [searchItems[0]!] });
    const add = vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule: twoDays, violations: [] });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getByRole('button', { name: '2일차' }));
    expect(screen.getByRole('heading', { name: /2일차/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '장소 추가' }));
    await userEvent.type(screen.getByLabelText('장소 검색'), '민락');
    await userEvent.click(screen.getByRole('button', { name: '검색' }));
    await userEvent.click(await screen.findByRole('button', { name: '추가' }));
    expect(add).toHaveBeenCalledWith('t1', expect.objectContaining({ dayNo: 2 }));
  });
  it('블록을 편집해도 열어 둔 장소 추가 패널은 닫지 않고, 추가가 성공하면 닫는다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    vi.spyOn(tripsApi, 'updateBlock').mockResolvedValue({ schedule, violations: [] });
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [searchItems[0]!] });
    vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getByRole('button', { name: '장소 추가' }));
    await userEvent.type(screen.getByLabelText('장소 검색'), '민락');
    await userEvent.click(screen.getByRole('button', { name: /감천/ }));
    await userEvent.click(screen.getByRole('button', { name: '체류시간 변경' }));
    await waitFor(() => expect(tripsApi.updateBlock).toHaveBeenCalled());
    expect(screen.getByLabelText('장소 검색')).toHaveValue('민락');
    await userEvent.click(screen.getByRole('button', { name: '검색' }));
    await userEvent.click(await screen.findByRole('button', { name: '추가' }));
    await waitFor(() => expect(screen.queryByLabelText('장소 검색')).not.toBeInTheDocument());
  });
  it('혼잡 신호가 없는 블록은 정보 부족으로 표시하고, 블록 경고 칩은 알림으로 읽지 않는다', async () => {
    const noCrowd = { ...schedule, days: [{ ...schedule.days[0]!, crowd: [] }] };
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule: noCrowd });
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    expect(screen.getAllByText('정보 부족')).toHaveLength(noCrowd.days[0]!.blocks.length);
    const [warning] = noCrowd.days[0]!.blocks.flatMap((block) => block.warnings);
    expect(screen.getByText(warning!.cause)).not.toHaveAttribute('role');
    // 칩 대신 요약 카드가 이 날 카드 경고 수를 한 번에 알린다.
    const onCards = noCrowd.days[0]!.blocks.reduce((count, block) => count + block.warnings.length, 0);
    expect(screen.getByRole('alert', { name: '일정 확인 필요' })).toHaveTextContent(`확인 필요 ${onCards}건`);
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  it('장소 추가가 실패하면 추가 패널과 검색 결과를 그대로 두고 오류를 보여 준다', async () => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [searchItems[0]!] });
    vi.spyOn(tripsApi, 'addBlock').mockRejectedValue(new Error('추가 실패'));
    render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    await screen.findByText('코스 타임라인');
    await userEvent.click(screen.getByRole('button', { name: '장소 추가' }));
    await userEvent.type(screen.getByLabelText('장소 검색'), '민락');
    await userEvent.click(screen.getByRole('button', { name: '검색' }));
    await userEvent.click(await screen.findByRole('button', { name: '추가' }));
    await waitFor(() => expect(tripsApi.addBlock).toHaveBeenCalled());
    expect(screen.getByLabelText('장소 검색')).toHaveValue('민락');
    expect(screen.getByRole('button', { name: '추가' })).toBeInTheDocument();
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
    expect(await screen.findByText(/체류 2시간/)).toBeInTheDocument();
    expect(tripsApi.updateBlock).toHaveBeenCalledWith('t1', schedule.days[0]!.blocks[0]!.id, { stayMin: 120 });
  });
  describe('경유지 추천 시트(UI-03)', () => {
    const [first, second] = schedule.days[0]!.blocks;
    const candidate = waypointCandidates[0]!;
    function renderPage() {
      render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    }

    it('추천을 열고 삽입이 실패하면 시트 안에 오류를 두고, 직접 검색으로 바꾼 뒤 일차를 바꾸면 닫힌다', async () => {
      const twoDays = { ...schedule, days: [schedule.days[0]!, { ...schedule.days[0]!, dayNo: 2, blocks: [], legs: [], crowd: [] }] };
      vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule: twoDays });
      const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
      const add = vi.spyOn(tripsApi, 'addBlock').mockRejectedValue(new Error('private raw error'));
      renderPage();
      await screen.findByText('코스 타임라인');
      // 기존 직접 검색 버튼은 그대로 남는다.
      expect(screen.getAllByRole('button', { name: '사이에 들를 곳 찾기' })[0]).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(screen.getAllByRole('button', { name: '추천 보기' })[0]!);
      const sheet = await screen.findByRole('dialog');
      expect(suggest).toHaveBeenCalledWith('t1', { fromBlockId: first!.id, toBlockId: second!.id, thresholdMin: 15 }, expect.anything());
      await userEvent.click(await within(sheet).findByRole('button', { name: `${candidate.place.name} 경유지로 추가` }));
      expect(add).toHaveBeenCalledWith('t1', {
        place: { placeId: candidate.place.id }, fromBlockId: first!.id, toBlockId: second!.id,
        isFixed: false, origin: 'SUGGESTED', stayMin: candidate.stayMin,
      });
      const alert = await within(sheet).findByRole('alert');
      expect(alert).not.toHaveTextContent('private raw error');
      expect(screen.getByRole('dialog')).toBe(sheet);
      expect(screen.getByRole('button', { name: '직전 편집 되돌리기' })).toBeDisabled();

      await userEvent.click(within(sheet).getByRole('button', { name: '직접 검색해서 넣기' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(screen.getByRole('region', { name: '경유지 추가' })).toBeInTheDocument();
      expect(screen.getAllByRole('button', { name: '사이에 들를 곳 찾기' })[0]).toHaveAttribute('aria-expanded', 'true');

      await userEvent.click(screen.getAllByRole('button', { name: '추천 보기' })[0]!);
      expect(await screen.findByRole('dialog')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: '2일차' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(screen.queryByRole('region', { name: '경유지 추가' })).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: '1일차' }));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('추천을 수락하면 새 일정을 반영하고 시트를 닫으며 되돌리기를 켠다', async () => {
      const changed = {
        ...schedule,
        days: [{ ...schedule.days[0]!, blocks: schedule.days[0]!.blocks.map((block, i) => i === 0 ? { ...block, stayMin: 120 } : block) }],
      };
      vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
      vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
      vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule: changed, violations: [] });
      renderPage();
      await screen.findByText('코스 타임라인');
      await userEvent.click(screen.getAllByRole('button', { name: '추천 보기' })[0]!);
      await userEvent.click(await screen.findByRole('button', { name: `${candidate.place.name} 경유지로 추가` }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(await screen.findByText(/체류 2시간/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '직전 편집 되돌리기' })).toBeEnabled();
    });

    it('삽입 요청 중에는 구간 버튼을 잠근다', async () => {
      vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
      vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
      let resolve!: (value: { schedule: typeof schedule; violations: [] }) => void;
      vi.spyOn(tripsApi, 'addBlock').mockReturnValue(new Promise((done) => { resolve = done; }));
      renderPage();
      await screen.findByText('코스 타임라인');
      await userEvent.click(screen.getAllByRole('button', { name: '추천 보기' })[0]!);
      await userEvent.click(await screen.findByRole('button', { name: `${candidate.place.name} 경유지로 추가` }));
      for (const button of screen.getAllByRole('button', { name: '추천 보기', hidden: true })) expect(button).toBeDisabled();
      for (const button of screen.getAllByRole('button', { name: '사이에 들를 곳 찾기', hidden: true })) expect(button).toBeDisabled();
      resolve({ schedule, violations: [] });
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    });
  });

  describe('블록 편집기 체류시간(fields.stayMin)', () => {
    function renderPage() {
      render(<MemoryRouter initialEntries={['/trips/t1']}><Routes><Route path="/trips/:tripId" element={<TimelinePage />} /></Routes></MemoryRouter>);
    }
    async function search(place: (typeof searchItems)[number]) {
      vi.spyOn(placesApi, 'search').mockResolvedValue({ places: [place] });
      await screen.findByText('코스 타임라인');
      await userEvent.click(screen.getByRole('button', { name: '장소 추가' }));
      await userEvent.type(screen.getByLabelText('장소 검색'), '민락');
      await userEvent.click(screen.getByRole('button', { name: '검색' }));
      return screen.findByRole('button', { name: '추가' });
    }

    it('서버가 체류시간을 물으면 머무를 시간 칸을 띄우고 고른 값으로 다시 보낸다', async () => {
      const message = '체류시간을 정할 수 없는 장소예요. 머무를 시간을 골라 주세요.';
      vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
      const add = vi.spyOn(tripsApi, 'addBlock')
        .mockRejectedValueOnce(parseErrorResponse(400, { error: { id: 'ERR-001', message, fields: { stayMin: message } } }))
        .mockResolvedValueOnce({ schedule, violations: [] });
      renderPage();
      const place = searchItems[0]!;
      expect(screen.queryByLabelText(`${place.name} 머무를 시간`)).not.toBeInTheDocument();
      await userEvent.click(await search(place));
      const select = await screen.findByLabelText(`${place.name} 머무를 시간`);
      expect(add).toHaveBeenLastCalledWith('t1', { place: { placeId: place.placeId }, isFixed: false, origin: 'USER', dayNo: 1 });
      expect(screen.getAllByText(message).length).toBeGreaterThan(0);
      await userEvent.selectOptions(select, '60');
      await userEvent.click(screen.getByRole('button', { name: '추가' }));
      await waitFor(() => expect(add).toHaveBeenLastCalledWith('t1', {
        place: { placeId: place.placeId }, isFixed: false, origin: 'USER', dayNo: 1, stayMin: 60,
      }));
      await waitFor(() => expect(screen.queryByLabelText('장소 검색')).not.toBeInTheDocument());
    });

    it('공공 DB에 없는 카카오 장소는 머무를 시간을 고르기 전에는 보내지 않는다', async () => {
      vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
      const add = vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] });
      renderPage();
      const place = searchItems.find((item) => item.placeId === null)!;
      await userEvent.click(await search(place));
      expect(await screen.findByText('머무를 시간을 골라 주세요.')).toHaveAttribute('role', 'alert');
      expect(add).not.toHaveBeenCalled();
      await userEvent.selectOptions(screen.getByLabelText(`${place.name} 머무를 시간`), '90');
      expect(screen.queryByText('머무를 시간을 골라 주세요.')).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: '추가' }));
      await waitFor(() => expect(add).toHaveBeenCalledWith('t1', {
        place: { kakaoPlaceId: place.kakaoPlaceId, placeUrl: place.placeUrl }, isFixed: false, origin: 'USER', dayNo: 1, stayMin: 90,
      }));
    });
  });
});
