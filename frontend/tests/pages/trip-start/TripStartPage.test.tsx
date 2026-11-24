import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, clearKakaoSession, getKakaoPlace, placesApi, tripsApi } from '@/api';
import { searchItems } from '@/api/mock/fixtures/places';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import TripStartPage from '@/pages/trip-start';
import { useTripDraft } from '@/store/tripDraft';
import type { InitialScheduleResponse } from '@/types/api';

function Timeline() {
  return <p>타임라인 {useParams().tripId}</p>;
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<TripStartPage />} />
        <Route path="/trips/:tripId" element={<Timeline />} />
        <Route path="/mood" element={<p>분위기 화면</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function setDates(start: string, end: string) {
  fireEvent.change(screen.getByLabelText('여행 시작일'), { target: { value: start } });
  fireEvent.change(screen.getByLabelText('여행 종료일'), { target: { value: end } });
}

/**
 * '민락'을 검색해 결과 세 곳(공공 DB 2곳, 카카오 1곳)을 모두 담는다.
 * 카카오 장소는 체류시간 근거가 없어 기본으로 머무를 시간 90분을 고른다(`stay: null`이면 고르지 않는다).
 */
async function pinAllSearchResults({ stay = '90' }: { stay?: string | null } = {}) {
  vi.spyOn(placesApi, 'search').mockResolvedValue({ places: searchItems });
  await userEvent.type(screen.getByLabelText('장소 검색'), '민락');
  await userEvent.click(screen.getByRole('button', { name: '검색' }));
  const results = await screen.findByRole('list', { name: '검색 결과' });
  for (const button of within(results).getAllByRole('button')) await userEvent.click(button);
  if (stay) await userEvent.selectOptions(screen.getByLabelText(`${searchItems[2]!.name} 머무를 시간`), stay);
}

function generated(saved: boolean, unplaced: InitialScheduleResponse['generation']['unplaced'] = []): InitialScheduleResponse {
  return { ...schedule, generation: { saved, confirmed: false, unplaced } };
}

function mockCourseApis() {
  return {
    create: vi.spyOn(tripsApi, 'create').mockResolvedValue({ tripId: 't9', sessionKey: 'k' }),
    initial: vi.spyOn(tripsApi, 'createInitialSchedule').mockResolvedValue(generated(true)),
    // 다시 시도할 때 이전 요청이 저장됐는지 확인하는 여행 조회(API-026). 기본은 빈 일정이다.
    get: vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule: { days: [], violations: [], conflicts: [] } }),
    addBlock: vi.spyOn(tripsApi, 'addBlock'),
  };
}

describe('UI-01 여행 시작', () => {
  beforeEach(() => {
    useTripDraft.getState().reset();
    clearKakaoSession();
  });

  describe('여행 조건 (FR-002, AC-002)', () => {
    it('한 줄 입력을 해석해 항목에 채우고, 채운 항목을 고칠 수 있다', async () => {
      const interpret = vi.spyOn(tripsApi, 'interpret').mockResolvedValue({
        conditions: { dates: { start: '2026-10-17', end: '2026-10-19' }, mode: 'CAR' },
        needsForm: false,
      });
      renderPage();
      await userEvent.type(screen.getByLabelText('여행 조건 한 줄 입력'), '10/17~19 2박 3일 자차');
      await userEvent.click(screen.getByRole('button', { name: '해석' }));

      expect(await screen.findByText(/해석한 조건을 아래에 채웠어요/)).toBeInTheDocument();
      expect(interpret.mock.calls[0]![0]).toEqual({ text: '10/17~19 2박 3일 자차' });
      expect(screen.getByLabelText('여행 시작일')).toHaveValue('2026-10-17');
      expect(screen.getByLabelText('여행 종료일')).toHaveValue('2026-10-19');
      expect(screen.getByText('2박 3일')).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: '자동차' })).toBeChecked();
      // 해석되지 않은 항목은 초기값을 유지한다.
      expect(screen.getByLabelText('하루 시작 시각')).toHaveValue('10:00');

      await userEvent.click(screen.getByRole('radio', { name: '도보 위주' }));
      expect(screen.getByRole('radio', { name: '도보 위주' })).toBeChecked();
      expect(screen.getByRole('radio', { name: '자동차' })).not.toBeChecked();
    });

    it.each([
      ['해석하지 못하면', () => vi.spyOn(tripsApi, 'interpret').mockResolvedValue({ conditions: {}, needsForm: true })],
      ['AI 호출이 실패하면', () => vi.spyOn(tripsApi, 'interpret').mockRejectedValue(new ApiError({ id: 'TIMEOUT' }))],
    ])('%s 항목별 입력으로 안내하고 날짜 입력으로 옮긴다', async (_name, mock) => {
      mock();
      renderPage();
      await userEvent.type(screen.getByLabelText('여행 조건 한 줄 입력'), '아무 말');
      await userEvent.click(screen.getByRole('button', { name: '해석' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('아래 항목을 직접 입력해 주세요');
      expect(screen.getByLabelText('여행 시작일')).toHaveFocus();
      expect(screen.getByLabelText('하루 종료 시각')).toHaveValue('19:00');
    });

    it('시작일을 종료일 뒤로 옮기면 종료일을 같은 날로 맞춘다', () => {
      renderPage();
      setDates('2026-10-17', '2026-10-18');
      fireEvent.change(screen.getByLabelText('여행 시작일'), { target: { value: '2026-10-20' } });
      expect(screen.getByLabelText('여행 종료일')).toHaveValue('2026-10-20');
      expect(screen.getByText('당일')).toBeInTheDocument();
    });
  });

  describe('꼭 갈 곳 (FR-001, AC-001)', () => {
    it('검색한 장소 3곳을 담으면 각 장소에 매칭 배지가 붙고, 공공 DB에 없는 장소도 담긴다', async () => {
      renderPage();
      expect(screen.getByRole('button', { name: '코스 만들기' })).toBeDisabled();
      await pinAllSearchResults();

      expect(screen.getByRole('heading', { name: '꼭 갈 곳 3' })).toBeInTheDocument();
      const pinned = useTripDraft.getState().pinned;
      expect(pinned.map((place) => place.kind)).toEqual(['PUBLIC', 'PUBLIC', 'KAKAO']);

      const items = screen.getAllByRole('button', { name: /빼기$/ }).map((button) => button.closest('li')!);
      expect(within(items[0]!).getByText('상세 정보 있음')).toBeInTheDocument();
      expect(within(items[2]!).getByText('민락 바다뷰 카페 (예시)')).toBeInTheDocument();
      expect(within(items[2]!).getByText('기본 정보만')).toBeInTheDocument();
      // D6: 카카오 장소의 이름·좌표는 이번 접속 메모리에만 둔다.
      expect(getKakaoPlace(searchItems[2]!.kakaoPlaceId)?.name).toBe('민락 바다뷰 카페 (예시)');
      expect(screen.getByRole('button', { name: '코스 만들기' })).toBeEnabled();
    });

    it('담은 장소를 빼면 목록과 개수에서 사라진다', async () => {
      renderPage();
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '민락회타운 빼기' }));
      expect(screen.getByRole('heading', { name: '꼭 갈 곳 2' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: '민락회타운 빼기' })).not.toBeInTheDocument();
    });

    it("당일 여행에는 일차 선택을 두지 않고, 여러 날이면 '알아서'와 날짜를 고르게 한다", async () => {
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      expect(screen.queryByLabelText('민락수변공원 방문 일차')).not.toBeInTheDocument();

      setDates('2026-10-17', '2026-10-18');
      const select = screen.getByLabelText('민락수변공원 방문 일차');
      // 기본은 '알아서'다. 서버가 여행 기간의 날짜를 차례로 시도한다.
      expect(select).toHaveValue('');
      expect(within(select).getAllByRole('option').map((option) => option.textContent)).toEqual([
        '일차 알아서',
        '1일차 · 10월 17일 (토)',
        '2일차 · 10월 18일 (일)',
      ]);
    });
  });

  describe('코스 만들기 (API-002 → API-009 최초 생성)', () => {
    it('조건과 담은 장소 전체를 한 번에 보내고, 저장되면 타임라인으로 이동하며 임시 상태를 비운다', async () => {
      const { create, initial, addBlock } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-18');
      await pinAllSearchResults();
      await userEvent.selectOptions(screen.getByLabelText('민락회타운 방문 일차'), '2');
      await userEvent.click(within(screen.getByRole('button', { name: '민락회타운 빼기' }).closest('li')!).getByRole('button', { name: '시간 정하기' }));
      fireEvent.change(screen.getByLabelText('민락회타운 도착 시각'), { target: { value: '12:00' } });
      fireEvent.change(screen.getByLabelText('민락회타운 출발 시각'), { target: { value: '13:30' } });
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      expect(create).toHaveBeenCalledWith({
        dates: { start: '2026-10-17', end: '2026-10-18' },
        dayStart: '10:00',
        dayEnd: '19:00',
        mode: 'TRANSIT',
      });
      expect(initial).toHaveBeenCalledTimes(1);
      expect(initial.mock.calls[0]!.slice(0, 2)).toEqual([
        't9',
        {
          policy: 'FIRST_FEASIBLE',
          selections: [
            { clientId: `public:${searchItems[0]!.placeId}`, place: { placeId: searchItems[0]!.placeId } },
            {
              clientId: `public:${searchItems[1]!.placeId}`,
              place: { placeId: searchItems[1]!.placeId },
              dayNo: 2,
              fixedWindow: { dayNo: 2, start: '12:00', end: '13:30' },
            },
            {
              clientId: `kakao:${searchItems[2]!.kakaoPlaceId}`,
              place: { kakaoPlaceId: searchItems[2]!.kakaoPlaceId, placeUrl: searchItems[2]!.placeUrl },
              stayMin: 90,
            },
          ],
        },
      ]);
      expect(addBlock).not.toHaveBeenCalled();
      expect(useTripDraft.getState().pinned).toEqual([]);
      // 타임라인에서 카카오 장소 이름을 보여 줄 수 있게 접속 메모리는 남긴다.
      expect(getKakaoPlace(searchItems[2]!.kakaoPlaceId)).not.toBeNull();
    });

    it('날짜가 없으면 요청하지 않고 어느 항목인지 알려 준다', async () => {
      const { create } = mockCourseApis();
      renderPage();
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      expect(screen.getByText('여행 날짜를 정해 주세요.')).toBeInTheDocument();
      expect(screen.getByText('입력한 내용을 다시 확인해 주세요.')).toBeInTheDocument();
      expect(screen.getByLabelText('여행 시작일')).toHaveAttribute('aria-invalid', 'true');
      expect(create).not.toHaveBeenCalled();

      // 고치면 오류가 바로 사라진다.
      setDates('2026-10-17', '2026-10-17');
      expect(screen.queryByText('여행 날짜를 정해 주세요.')).not.toBeInTheDocument();
    });

    it('시간을 정하기로 한 장소의 시각이 비어 있으면 요청하지 않는다', async () => {
      const { create } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getAllByRole('button', { name: '시간 정하기' })[0]!);
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      expect(screen.getByText('도착·출발 시각을 모두 정해 주세요.')).toBeInTheDocument();
      expect(create).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole('button', { name: '시간 빼기' }));
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    });

    it("여러 날 여행에서 시간을 정한 장소의 일차가 '알아서'면 일차를 고르게 한다", async () => {
      const { create } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-18');
      await pinAllSearchResults();
      await userEvent.click(screen.getAllByRole('button', { name: '시간 정하기' })[0]!);
      fireEvent.change(screen.getByLabelText('민락수변공원 도착 시각'), { target: { value: '10:00' } });
      fireEvent.change(screen.getByLabelText('민락수변공원 출발 시각'), { target: { value: '11:00' } });
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      expect(screen.getByText('시간을 정한 장소는 일차를 골라 주세요.')).toBeInTheDocument();
      expect(screen.getByLabelText('민락수변공원 방문 일차')).toHaveAttribute('aria-invalid', 'true');
      expect(create).not.toHaveBeenCalled();
    });

    it('공공 DB에 없는 카카오 장소는 머무를 시간을 고르지 않으면 요청하지 않는다(#18 PM 결정 4)', async () => {
      const { create, initial } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults({ stay: null });

      // 공공 DB 장소는 서버가 장소별 체류시간을 써서 고르는 칸이 없다. 기본값도 고르지 않은 상태다.
      expect(screen.queryByLabelText(`${searchItems[0]!.name} 머무를 시간`)).not.toBeInTheDocument();
      const stay = screen.getByLabelText(`${searchItems[2]!.name} 머무를 시간`);
      expect(stay).toHaveValue('');

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(screen.getByText('머무를 시간을 골라 주세요.')).toBeInTheDocument();
      expect(stay).toHaveAttribute('aria-invalid', 'true');
      expect(create).not.toHaveBeenCalled();

      await userEvent.selectOptions(stay, '120');
      expect(screen.queryByText('머무를 시간을 골라 주세요.')).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await waitFor(() => expect(initial).toHaveBeenCalledTimes(1));
      expect(initial.mock.calls[0]![1].selections[2]).toMatchObject({ stayMin: 120 });
    });

    it('카카오 장소의 시간을 정하면 머무를 시간 칸 없이 그 시간을 체류시간으로 보낸다', async () => {
      const { initial } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults({ stay: null });
      const name = searchItems[2]!.name;
      await userEvent.click(screen.getAllByRole('button', { name: '시간 정하기' })[2]!);
      expect(screen.queryByLabelText(`${name} 머무를 시간`)).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText(`${name} 도착 시각`), { target: { value: '15:00' } });
      fireEvent.change(screen.getByLabelText(`${name} 출발 시각`), { target: { value: '16:30' } });

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await waitFor(() => expect(initial).toHaveBeenCalledTimes(1));
      // 당일 여행이라 일차는 1일차로 정해진다.
      expect(initial.mock.calls[0]![1].selections[2]).toMatchObject({
        stayMin: 90,
        fixedWindow: { dayNo: 1, start: '15:00', end: '16:30' },
      });
    });

    it('여행 기간을 줄이면 사라진 일차의 장소는 마지막 날로 보낸다', async () => {
      const { initial } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-19');
      await pinAllSearchResults();
      await userEvent.selectOptions(screen.getByLabelText('민락수변공원 방문 일차'), '3');
      setDates('2026-10-17', '2026-10-18');
      expect(screen.getByLabelText('민락수변공원 방문 일차')).toHaveValue('2');

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await screen.findByText('타임라인 t9');
      expect(initial.mock.calls[0]![1].selections[0]).toMatchObject({ dayNo: 2 });
    });

    it('여행 생성이 실패하면 오류를 보여 주고 입력을 그대로 둔다', async () => {
      const { create } = mockCourseApis();
      create.mockRejectedValue(new ApiError({ id: 'NETWORK' }));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(new ApiError({ id: 'NETWORK' }).message);
      expect(screen.getByRole('heading', { name: '꼭 갈 곳 3' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '코스 만들기' })).toBeEnabled();
    });

    it('넣지 못한 장소가 있으면 저장하지 않고 그 장소에 이유를 보여 주며, 고친 뒤 같은 여행에 다시 보낸다', async () => {
      const { create, initial } = mockCourseApis();
      const reason = { type: 'STAY_NEEDS_CHECK', cause: '체류시간 근거 확인이 필요합니다.' };
      const publicKey = `public:${searchItems[1]!.placeId}`;
      const other = { type: 'DAY_FULL', cause: '하루 일정 안에 넣을 수 없습니다.' };
      initial.mockResolvedValueOnce(generated(false, [
        { clientId: `public:${searchItems[0]!.placeId}`, reason: other },
        { clientId: publicKey, reason },
      ]));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      const name = searchItems[1]!.name;
      // 공공 DB 장소는 처음에는 머무를 시간을 묻지 않는다.
      expect(screen.queryByLabelText(`${name} 머무를 시간`)).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText(/일정에 넣지 못한 장소가 있어 아직 저장하지 않았어요/)).toBeInTheDocument();
      // 넣지 못한 장소에는 서버가 준 이유를 보여 준다.
      const first = screen.getByRole('button', { name: `${searchItems[0]!.name} 빼기` }).closest('li')!;
      expect(within(first).getByText(other.cause)).toBeInTheDocument();
      // 체류시간 근거가 없다고 한 장소에는 머무를 시간 칸과 할 일을 보여 준다(#18 PM 결정 4).
      const item = screen.getByRole('button', { name: `${name} 빼기` }).closest('li')!;
      expect(within(item).getByText('머무를 시간을 골라 주세요.')).toBeInTheDocument();
      const stay = within(item).getByLabelText(`${name} 머무를 시간`);
      expect(screen.queryByText('타임라인 t9')).not.toBeInTheDocument();

      await userEvent.selectOptions(stay, '60');
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      // 저장되지 않은 빈 여행을 다시 쓰고, 선택 전체를 다시 보낸다.
      expect(create).toHaveBeenCalledTimes(1);
      expect(initial).toHaveBeenCalledTimes(2);
      expect(initial.mock.calls[1]![0]).toBe('t9');
      expect(initial.mock.calls[1]![1].selections.find((item) => item.clientId === publicKey)).toMatchObject({ stayMin: 60 });
    });

    it('고정 시각 충돌(ERR-009)이면 이유를 보여 주고, 여행 조건이 같으면 같은 여행으로 다시 만든다', async () => {
      const { create, initial } = mockCourseApis();
      initial.mockRejectedValueOnce(new ApiError({ id: 'ERR-009', status: 409 }));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('시간 안에 모두 넣을 수 없어요');
      expect(alert).toHaveTextContent('다시 누르면 같은 여행으로 이어서 만들어요');

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      expect(create).toHaveBeenCalledTimes(1);
    });

    it('실패 뒤 여행 조건을 바꾸면 이전 여행을 쓰지 않고 새 여행을 만든다', async () => {
      const { create, initial } = mockCourseApis();
      initial.mockRejectedValueOnce(new ApiError({ id: 'ERR-009', status: 409 }));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await screen.findByRole('alert');

      await userEvent.click(screen.getByRole('radio', { name: '자동차' }));
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await screen.findByText('타임라인 t9');
      expect(create).toHaveBeenCalledTimes(2);
      expect(create.mock.calls[1]![0]).toMatchObject({ mode: 'CAR' });
    });

    it('응답을 못 받은 이전 요청이 저장됐는데 그 뒤 고친 내용이 있으면, 조용히 이동하지 않고 알린다', async () => {
      const { initial, get } = mockCourseApis();
      initial.mockRejectedValueOnce(new ApiError({ id: 'TIMEOUT' }));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText(/다시 누르면 같은 여행으로 이어서 만들어요/)).toBeInTheDocument();

      // 그 사이 첫 요청이 저장을 마쳤다. 사용자는 체류시간을 바꿔 다시 누른다.
      get.mockResolvedValue({ trip, schedule });
      await userEvent.selectOptions(screen.getByLabelText(`${searchItems[2]!.name} 머무를 시간`), '120');
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      expect(await screen.findByText('이전 요청으로 코스가 이미 만들어졌어요')).toBeInTheDocument();
      // 고친 선택은 보내지 않았고, 확인한 뒤 타임라인으로 간다.
      expect(initial).toHaveBeenCalledTimes(1);
      await userEvent.click(screen.getByRole('button', { name: '타임라인에서 확인하기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
    });

    it('이전 요청이 저장됐고 고친 내용이 없으면 바로 타임라인으로 간다', async () => {
      const { initial, get } = mockCourseApis();
      initial.mockRejectedValueOnce(new ApiError({ id: 'TIMEOUT' }));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await screen.findByText(/다시 누르면 같은 여행으로 이어서 만들어요/);

      get.mockResolvedValue({ trip, schedule });
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
    });

    it('장소의 계획을 고치면 그 장소의 미배치 이유를 지운다', async () => {
      const { initial } = mockCourseApis();
      const other = { type: 'DAY_FULL', cause: '하루 일정 안에 넣을 수 없습니다.' };
      initial.mockResolvedValueOnce(generated(false, [{ clientId: `public:${searchItems[0]!.placeId}`, reason: other }]));
      renderPage();
      setDates('2026-10-17', '2026-10-18');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText(other.cause)).toBeInTheDocument();

      await userEvent.selectOptions(screen.getByLabelText(`${searchItems[0]!.name} 방문 일차`), '2');
      expect(screen.queryByText(other.cause)).not.toBeInTheDocument();
    });

    it('저장되지 않았는데 표시할 장소가 없으면 일반 안내를 보여 준다', async () => {
      const { initial } = mockCourseApis();
      initial.mockResolvedValueOnce(generated(false, []));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText('일정을 저장하지 못했어요. 장소나 시간을 바꿔 다시 눌러 주세요.')).toBeInTheDocument();
    });

    it('응답을 못 받았지만 서버에 저장됐으면 여행 조회로 확인하고 타임라인으로 간다', async () => {
      const { initial, get } = mockCourseApis();
      initial.mockRejectedValueOnce(new ApiError({ id: 'TIMEOUT' }));
      get.mockResolvedValue({ trip, schedule });
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      expect(get).toHaveBeenCalledWith('t9');
    });
  });

  describe('고른 분위기 (FR-015)', () => {
    const sea = { code: 'SEA_VIEW', label: '바다 전망' };

    it('UI-08에서 고른 분위기를 보여 주고 지울 수 있다', async () => {
      useTripDraft.getState().setMood({ tags: [sea], avoid: ['실내 제외'] });
      renderPage();
      const mood = screen.getByRole('group', { name: '고른 분위기' });
      expect(within(mood).getByText('바다 전망 · 실내 제외')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /고른 분위기 바꾸기/ })).toBeInTheDocument();

      await userEvent.click(within(mood).getByRole('button', { name: '분위기 지우기' }));
      expect(screen.queryByRole('group', { name: '고른 분위기' })).not.toBeInTheDocument();
      expect(screen.getByRole('link', { name: /원하는 분위기로 찾기/ })).toBeInTheDocument();
      expect(useTripDraft.getState().conditions.prefs).toBeUndefined();
    });

    it('코스를 만들 때 고른 태그와 피할 조건을 여행 조건(API-002 prefs)으로 보낸다', async () => {
      const { create } = mockCourseApis();
      useTripDraft.getState().setMood({ tags: [sea], avoid: ['실내 제외'] });
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      expect(create.mock.calls[0]![0]).toMatchObject({ prefs: { tags: ['SEA_VIEW'], avoid: ['실내 제외'] } });
      // 여행을 만들고 나면 초안과 함께 분위기도 비운다.
      expect(useTripDraft.getState().mood).toBeNull();
    });
  });

  it('분위기로 찾기 화면으로 이동해도 담은 장소가 유지된다', async () => {
    renderPage();
    await pinAllSearchResults();
    await userEvent.click(screen.getByRole('link', { name: /원하는 분위기로 찾기/ }));
    expect(screen.getByText('분위기 화면')).toBeInTheDocument();
    expect(useTripDraft.getState().pinned).toHaveLength(3);
  });
});
