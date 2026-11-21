import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, clearKakaoSession, getKakaoPlace, placesApi, tripsApi } from '@/api';
import { searchItems } from '@/api/mock/fixtures/places';
import { schedule } from '@/api/mock/fixtures/schedule';
import TripStartPage from '@/pages/trip-start';
import { useTripDraft } from '@/store/tripDraft';

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

function mockCourseApis() {
  return {
    create: vi.spyOn(tripsApi, 'create').mockResolvedValue({ tripId: 't9', sessionKey: 'k' }),
    addBlock: vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] }),
    generate: vi.spyOn(tripsApi, 'generateSchedule').mockResolvedValue(schedule),
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

    it('당일 여행에는 일차 선택을 두지 않고, 여러 날이면 날짜와 함께 고르게 한다', async () => {
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      expect(screen.queryByLabelText('민락수변공원 방문 일차')).not.toBeInTheDocument();

      setDates('2026-10-17', '2026-10-18');
      const select = screen.getByLabelText('민락수변공원 방문 일차');
      expect(within(select).getAllByRole('option').map((option) => option.textContent)).toEqual([
        '1일차 · 10월 17일 (토)',
        '2일차 · 10월 18일 (일)',
      ]);
    });
  });

  describe('코스 만들기', () => {
    it('조건과 담은 장소를 보내고 타임라인으로 이동하며 임시 상태를 비운다', async () => {
      const { create, addBlock, generate } = mockCourseApis();
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
      expect(addBlock.mock.calls.map(([, body]) => body)).toEqual([
        { dayNo: 1, place: { placeId: searchItems[0]!.placeId }, origin: 'USER', isFixed: false },
        {
          dayNo: 2,
          place: { placeId: searchItems[1]!.placeId },
          origin: 'USER',
          isFixed: true,
          fixedWindow: { dayNo: 2, start: '12:00', end: '13:30' },
        },
        {
          dayNo: 1,
          place: { kakaoPlaceId: searchItems[2]!.kakaoPlaceId, placeUrl: searchItems[2]!.placeUrl },
          origin: 'USER',
          stayMin: 90,
          isFixed: false,
        },
      ]);
      expect(generate).toHaveBeenCalledWith('t9');
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

    it('공공 DB에 없는 카카오 장소는 머무를 시간을 고르지 않으면 요청하지 않는다(#18 PM 결정 4)', async () => {
      const { create, addBlock } = mockCourseApis();
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
      await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
      expect(addBlock.mock.calls.at(-1)![1]).toMatchObject({ stayMin: 120, isFixed: false });
    });

    it('카카오 장소의 시간을 정하면 머무를 시간 칸 없이 그 시간을 체류시간으로 보낸다', async () => {
      const { addBlock } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults({ stay: null });
      const name = searchItems[2]!.name;
      await userEvent.click(screen.getAllByRole('button', { name: '시간 정하기' })[2]!);
      expect(screen.queryByLabelText(`${name} 머무를 시간`)).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText(`${name} 도착 시각`), { target: { value: '15:00' } });
      fireEvent.change(screen.getByLabelText(`${name} 출발 시각`), { target: { value: '16:30' } });

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await waitFor(() => expect(addBlock).toHaveBeenCalledTimes(3));
      expect(addBlock.mock.calls[2]![1]).toMatchObject({ stayMin: 90, isFixed: true });
    });

    it('여행 기간을 줄이면 사라진 일차의 장소는 마지막 날로 보낸다', async () => {
      const { addBlock } = mockCourseApis();
      renderPage();
      setDates('2026-10-17', '2026-10-19');
      await pinAllSearchResults();
      await userEvent.selectOptions(screen.getByLabelText('민락수변공원 방문 일차'), '3');
      setDates('2026-10-17', '2026-10-18');
      expect(screen.getByLabelText('민락수변공원 방문 일차')).toHaveValue('2');

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await screen.findByText('타임라인 t9');
      expect(addBlock.mock.calls[0]![1]).toMatchObject({ dayNo: 2 });
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

    it('장소 추가가 중간에 실패한 뒤 다시 누르면 같은 여행에 남은 장소만 이어서 담는다', async () => {
      const { create, addBlock } = mockCourseApis();
      addBlock
        .mockResolvedValueOnce({ schedule, violations: [] })
        .mockRejectedValueOnce(new ApiError({ id: 'NETWORK' }))
        .mockResolvedValue({ schedule, violations: [] });
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('다시 누르면 남은 장소부터 이어서 담아요');

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      expect(create).toHaveBeenCalledTimes(1);
      // 첫 장소는 한 번만, 실패한 둘째 장소는 다시, 셋째 장소는 처음 보낸다.
      expect(addBlock.mock.calls.map(([tripId, body]) => [tripId, body.place])).toEqual([
        ['t9', { placeId: searchItems[0]!.placeId }],
        ['t9', { placeId: searchItems[1]!.placeId }],
        ['t9', { placeId: searchItems[1]!.placeId }],
        ['t9', { kakaoPlaceId: searchItems[2]!.kakaoPlaceId, placeUrl: searchItems[2]!.placeUrl }],
      ]);
    });

    it('서버가 공공 DB 장소의 체류시간을 요구하면(fields.stayMin) 그 장소에 머무를 시간을 고르게 하고 이어서 담는다', async () => {
      const { create, addBlock } = mockCourseApis();
      const message = '체류시간을 정할 수 없는 장소예요. 머무를 시간을 골라 주세요.';
      addBlock
        .mockResolvedValueOnce({ schedule, violations: [] })
        .mockRejectedValueOnce(new ApiError({ id: 'ERR-001', status: 400, message, fields: { stayMin: message } }))
        .mockResolvedValue({ schedule, violations: [] });
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      const name = searchItems[1]!.name;
      // 공공 DB 장소는 처음에는 머무를 시간을 묻지 않는다.
      expect(screen.queryByLabelText(`${name} 머무를 시간`)).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText(new RegExp(message))).toBeInTheDocument();
      const stay = screen.getByLabelText(`${name} 머무를 시간`);
      expect(stay).toHaveValue('');
      expect(screen.getByText('머무를 시간을 골라 주세요.')).toBeInTheDocument();

      // 고르지 않고 다시 누르면 요청하지 않는다.
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(addBlock).toHaveBeenCalledTimes(2);

      await userEvent.selectOptions(stay, '60');
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      // 체류시간만 바꿨으므로 새 여행을 만들지 않고 실패한 장소부터 이어 간다.
      expect(create).toHaveBeenCalledTimes(1);
      expect(addBlock.mock.calls.map(([, body]) => [body.place, body.stayMin])).toEqual([
        [{ placeId: searchItems[0]!.placeId }, undefined],
        [{ placeId: searchItems[1]!.placeId }, undefined],
        [{ placeId: searchItems[1]!.placeId }, 60],
        [{ kakaoPlaceId: searchItems[2]!.kakaoPlaceId, placeUrl: searchItems[2]!.placeUrl }, 90],
      ]);
    });

    it('장소 추가 실패 뒤 입력을 바꾸면 이어 쓰지 않고 새 여행을 만든다', async () => {
      const { create, addBlock } = mockCourseApis();
      addBlock.mockRejectedValueOnce(new ApiError({ id: 'NETWORK' })).mockResolvedValue({ schedule, violations: [] });
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

    it('일정 계산만 실패하면(ERR-009) 만든 여행의 타임라인으로 갈 수 있게 한다', async () => {
      const { create, generate } = mockCourseApis();
      generate.mockRejectedValue(new ApiError({ id: 'ERR-009', status: 409 }));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent('여행은 만들었지만 일정 계산을 마치지 못했어요');
      expect(alert).toHaveTextContent('시간 안에 모두 넣을 수 없어요');
      // 같은 입력으로 여행을 또 만들지 않게 만들기 버튼 대신 이동 버튼을 둔다.
      expect(screen.queryByRole('button', { name: '코스 만들기' })).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: '타임라인에서 확인하기' }));
      expect(await screen.findByText('타임라인 t9')).toBeInTheDocument();
      expect(create).toHaveBeenCalledTimes(1);
    });

    it('일정 계산 실패 뒤 입력을 바꾸면 다시 코스를 만들 수 있다', async () => {
      const { generate } = mockCourseApis();
      generate.mockRejectedValue(new ApiError({ id: 'ERR-009', status: 409 }));
      renderPage();
      setDates('2026-10-17', '2026-10-17');
      await pinAllSearchResults();
      await userEvent.click(screen.getByRole('button', { name: '코스 만들기' }));
      await screen.findByRole('button', { name: '타임라인에서 확인하기' });

      setDates('2026-10-17', '2026-10-18');
      expect(screen.getByRole('button', { name: '코스 만들기' })).toBeEnabled();
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
