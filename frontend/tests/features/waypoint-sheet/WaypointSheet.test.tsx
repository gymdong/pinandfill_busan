import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { defaultMessage, tripsApi } from '@/api';
import { parseErrorResponse } from '@/api/errors';
import { placeSummaries } from '@/api/mock/fixtures/places';
import { schedule } from '@/api/mock/fixtures/schedule';
import { WaypointSheet, type WaypointSheetProps } from '@/features/waypoint-sheet/WaypointSheet';
import type { SuggestWaypointsResponse, WaypointCandidate } from '@/types/api';

const candidate: WaypointCandidate = {
  place: placeSummaries.gamcheon, detourMin: 10, stayMin: 40, crowd: null, reason: '공공 장소 추천 이유',
};
function props(): WaypointSheetProps {
  return { tripId: 'trip', between: { fromBlockId: 'a', toBlockId: 'b' }, disabled: false, onChange: vi.fn(async (action) => { await action(); }), onClose: vi.fn() };
}
function deferred() {
  let resolve!: (value: SuggestWaypointsResponse) => void;
  const promise = new Promise<SuggestWaypointsResponse>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('WaypointSheet', () => {
  it('기본 15분으로 조회하고 이동·체류·혼잡 부족·추천 이유를 표시한다', async () => {
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
    render(<WaypointSheet {...props()} />);
    expect(await screen.findByText(candidate.place.name)).toBeInTheDocument();
    expect(suggest).toHaveBeenCalledWith('trip', { fromBlockId: 'a', toBlockId: 'b', thresholdMin: 15 }, { signal: expect.any(AbortSignal) });
    expect(screen.getByText('+10분')).toBeInTheDocument();
    expect(screen.getByText('머무는 시간 40분')).toBeInTheDocument();
    expect(screen.getByText('정보 부족')).toBeInTheDocument();
    expect(screen.getByText(candidate.reason)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '15분' })).toBeChecked();
  });

  it('10/30분 변경은 해당 임계값으로 다시 조회하고 빈 결과 안내를 제공한다', async () => {
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [] });
    render(<WaypointSheet {...props()} />);
    expect(await screen.findByText(/들를 곳이 없어요/)).toBeInTheDocument();
    expect(screen.getByText('우회 시간을 늘려 다시 찾아보세요.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: '10분' }));
    await waitFor(() => expect(suggest).toHaveBeenLastCalledWith('trip', expect.objectContaining({ thresholdMin: 10 }), expect.anything()));
    await userEvent.click(screen.getByRole('radio', { name: '30분' }));
    expect(await screen.findByText('다른 구간에서 찾아보세요.')).toBeInTheDocument();
    expect(suggest).toHaveBeenLastCalledWith('trip', expect.objectContaining({ thresholdMin: 30 }), expect.anything());
  });

  it('수락은 표시한 stayMin을 포함한 API-006 입력을 부모 변경 핸들러로 전달한다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
    const add = vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] });
    const input = props();
    render(<WaypointSheet {...input} />);
    await userEvent.click(await screen.findByRole('button', { name: `${candidate.place.name} 일정에 넣기` }));
    expect(input.onChange).toHaveBeenCalledTimes(1);
    expect(add).toHaveBeenCalledExactlyOnceWith('trip', { place: { placeId: candidate.place.id }, fromBlockId: 'a', toBlockId: 'b', isFixed: false, origin: 'SUGGESTED', stayMin: candidate.stayMin });
  });

  it('부모가 편집 중이면 임계값과 추가 버튼을 잠근다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
    render(<WaypointSheet {...props()} disabled />);
    expect(await screen.findByRole('button', { name: `${candidate.place.name} 일정에 넣기` })).toBeDisabled();
    expect(screen.getByRole('radio', { name: '10분' })).toBeDisabled();
  });

  it('최대 3개만 서버 순서대로 표시한다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [1, 2, 3, 4].map((n) => ({ ...candidate, place: { ...candidate.place, id: `id${n}`, name: `후보${n}` } })) });
    render(<WaypointSheet {...props()} />);
    await screen.findByText('후보1');
    expect(screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent)).toEqual(['후보1', '후보2', '후보3']);
    expect(screen.queryByText('후보4')).not.toBeInTheDocument();
  });

  it('조회 오류는 재시도할 수 있고 원시 예외 내용을 표시하지 않는다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockRejectedValueOnce(new Error('secret raw payload')).mockResolvedValueOnce({ candidates: [candidate] });
    render(<WaypointSheet {...props()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('들를 곳을 불러오지 못했어요.');
    expect(screen.queryByText(/secret raw/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText(candidate.place.name)).toBeInTheDocument();
  });

  it('조회 오류는 정제된 ApiError 문구로 표시한다', async () => {
    vi.spyOn(tripsApi, 'suggestWaypoints').mockRejectedValueOnce(new Error('Traceback: provider exploded'));
    const { unmount } = render(<WaypointSheet {...props()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(`들를 곳을 불러오지 못했어요. ${defaultMessage('UNKNOWN')}`);
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
    unmount();
    vi.spyOn(tripsApi, 'suggestWaypoints').mockRejectedValueOnce(parseErrorResponse(503, { error: { id: 'ERR-017', message: '일정 계산에 필요한 장소·경로 정보를 확인해 주세요.' } }));
    render(<WaypointSheet {...props()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('들를 곳을 불러오지 못했어요. 일정 계산에 필요한 장소·경로 정보를 확인해 주세요.');
  });

  it('임계값이 바뀌면 이전 요청을 취소하고 늦은 결과를 무시한다', async () => {
    const old = deferred();
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockReturnValueOnce(old.promise).mockResolvedValueOnce({ candidates: [] });
    render(<WaypointSheet {...props()} />);
    expect(screen.getByRole('status')).toHaveTextContent('들를 곳을 찾는 중');
    await userEvent.click(screen.getByRole('radio', { name: '30분' }));
    await screen.findByText(/들를 곳이 없어요/);
    expect(suggest.mock.calls[0]![2]!.signal!.aborted).toBe(true);
    await act(async () => old.resolve({ candidates: [candidate] }));
    expect(screen.queryByText(candidate.place.name)).not.toBeInTheDocument();
  });

  it('다른 구간으로 바꾸면 기본 임계값으로 재조회하고 이전 후보를 숨긴다', async () => {
    const next = deferred();
    vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValueOnce({ candidates: [candidate] }).mockResolvedValueOnce({ candidates: [candidate] }).mockReturnValueOnce(next.promise);
    const input = props();
    const view = render(<WaypointSheet {...input} />);
    await screen.findByText(candidate.place.name);
    await userEvent.click(screen.getByRole('radio', { name: '30분' }));
    await screen.findByText(candidate.place.name);
    view.rerender(<WaypointSheet {...input} between={{ fromBlockId: 'b', toBlockId: 'c' }} />);
    expect(screen.getByRole('radio', { name: '15분' })).toBeChecked();
    expect(screen.queryByText(candidate.place.name)).not.toBeInTheDocument();
    await act(async () => next.resolve({ candidates: [] }));
  });

  it('닫기는 부모에게 전달하고 언마운트하면 요청을 취소한다', async () => {
    const pending = deferred();
    const suggest = vi.spyOn(tripsApi, 'suggestWaypoints').mockReturnValue(pending.promise);
    const input = props();
    const view = render(<WaypointSheet {...input} />);
    await userEvent.click(screen.getByRole('button', { name: '닫기' }));
    expect(input.onClose).toHaveBeenCalledOnce();
    view.unmount();
    expect(suggest.mock.calls[0]![2]!.signal!.aborted).toBe(true);
    await act(async () => pending.resolve({ candidates: [candidate] }));
  });
it('삽입 실패를 시트 내부에 표시하고 같은 후보로 재시도한다', async () => {
  vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
  const add = vi.spyOn(tripsApi, 'addBlock').mockRejectedValueOnce(new Error('private raw error')).mockResolvedValueOnce({ schedule, violations: [] });
  const input = props();
  input.onChange = vi.fn(async (action) => { try { await action(); input.onClose(); } catch { /* parent owns timeline error */ } });
  render(<WaypointSheet {...input} />);
  const button = await screen.findByRole('button', { name: `${candidate.place.name} 일정에 넣기` });
  await userEvent.click(button);
  const alert = await screen.findByRole('alert');
  expect(screen.getByRole('dialog').contains(alert)).toBe(true);
  expect(alert).not.toHaveTextContent('private raw error');
  expect(input.onClose).not.toHaveBeenCalled();
  await userEvent.click(button);
  await waitFor(() => expect(input.onClose).toHaveBeenCalledOnce());
  expect(add).toHaveBeenCalledTimes(2);
});

it('삽입 실패 뒤 임계값을 바꾸면 이전 삽입 오류를 지운다', async () => {
  vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
  vi.spyOn(tripsApi, 'addBlock').mockRejectedValue(new Error('private raw error'));
  render(<WaypointSheet {...props()} />);
  await userEvent.click(await screen.findByRole('button', { name: `${candidate.place.name} 일정에 넣기` }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('radio', { name: '30분' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
});

it('빈 추천에서도 직접 검색 진입점을 제공하며 삽입하지 않는다', async () => {
  vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [] });
  const add = vi.spyOn(tripsApi, 'addBlock');
  const direct = vi.fn();
  render(<WaypointSheet {...props()} onDirectSearch={direct} />);
  await screen.findByText(/들를 곳이 없어요/);
  await userEvent.click(screen.getByRole('button', { name: '원하는 곳 직접 찾아 넣기' }));
  expect(direct).toHaveBeenCalledOnce();
  expect(add).not.toHaveBeenCalled();
});

});

it('구간 이름을 제목으로, 뒤의 고정 장소를 그대로라고 보여 준다(원칙 5)', async () => {
  vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
  render(<WaypointSheet {...props()} fromName="용두산 공원" toName="광안리해수욕장" keptFixed={[{ name: '부산시립미술관', start: '16:00' }]} />);
  expect(screen.getByRole('dialog', { name: '용두산 공원 → 광안리해수욕장 사이' })).toBeInTheDocument();
  expect(await screen.findByText('넣어도 그대로: 부산시립미술관 16:00')).toBeInTheDocument();
});


it('이미 일정에 있는 장소는 후보에서 거르고, 정렬 기준을 문구로 밝힌다', async () => {
  vi.spyOn(tripsApi, 'suggestWaypoints').mockResolvedValue({ candidates: [candidate] });
  render(<WaypointSheet {...props()} excludePlaceIds={[candidate.place.id]} />);
  expect(await screen.findByText(/들를 곳이 없어요/)).toBeInTheDocument();
  expect(screen.queryByText(candidate.place.name)).not.toBeInTheDocument();
  expect(screen.getByText(/우회 시간과 예상 혼잡을 함께 따져 골랐어요/)).toBeInTheDocument();
});
