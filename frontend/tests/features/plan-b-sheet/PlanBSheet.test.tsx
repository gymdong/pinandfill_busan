import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, tripsApi } from '@/api';
import { placeSummaries } from '@/api/mock/fixtures/places';
import { schedule } from '@/api/mock/fixtures/schedule';
import { PlanBSheet, type PlanBSheetProps } from '@/features/plan-b-sheet/PlanBSheet';
import type { CrowdSummary, PlanBResponse } from '@/types/api';

const busy: CrowdSummary = { grade: '붐빔', confidence: '중간', asOf: '2026-10-01T00:00:00+09:00', sources: ['DATA-04'] };
const free: CrowdSummary = { ...busy, grade: '여유' };
const response: PlanBResponse = {
  blockId: 'b1',
  trigger: 'CROWD',
  crowd: busy,
  options: [
    { id: 'KEEP', kind: 'KEEP', available: true, extraMinutes: 0, hoursConflict: false, arriveAt: '18:53', departAt: '19:38', crowd: busy },
    { id: 'REORDER:b1', kind: 'REORDER', available: false, extraMinutes: null, hoursConflict: false, note: '고정 시각을 지키면서 덜 붐비게 되는 순서가 없어요.' },
    { id: 'REPLACE:b1:x', kind: 'REPLACE', available: true, extraMinutes: 3, hoursConflict: false, arriveAt: '18:56', departAt: '20:26', crowd: free, place: placeSummaries.huinnyeoul },
  ],
};

function props(): PlanBSheetProps {
  return { tripId: 'trip', blockId: 'b1', placeName: '용두산 공원', disabled: false, onChange: vi.fn(async (action) => { await action(); }), onClose: vi.fn() };
}

describe('PlanBSheet', () => {
  it('3안을 이동시간·영업시간 충돌·예상 혼잡과 함께 보여 주고, 고를 수 없는 안은 이유를 적는다', async () => {
    const get = vi.spyOn(tripsApi, 'getPlanB').mockResolvedValue(response);
    render(<PlanBSheet {...props()} />);
    expect(await screen.findByRole('heading', { name: `대체 장소: ${placeSummaries.huinnyeoul.name}` })).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('trip', 'b1', { signal: expect.any(AbortSignal) });
    expect(screen.getByText('지금 시각은 예상 붐빔이에요. 고르기 전에는 일정을 바꾸지 않아요.')).toBeInTheDocument();
    expect(screen.getByText('고정 시각을 지키면서 덜 붐비게 되는 순서가 없어요.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '순서 바꾸기 적용' })).not.toBeInTheDocument();
    expect(screen.getByText(/이동 \+3분/)).toBeInTheDocument();
    expect(screen.getAllByText(/영업시간 충돌 없음/)).toHaveLength(2);
  });

  it('대체 장소를 고르면 API-015 로 적용하고 알림 문구를 넘긴다', async () => {
    vi.spyOn(tripsApi, 'getPlanB').mockResolvedValue(response);
    const apply = vi.spyOn(tripsApi, 'applyPlanB').mockResolvedValue({ schedule, violations: [] });
    const input = props();
    render(<PlanBSheet {...input} />);
    await userEvent.click(await screen.findByRole('button', { name: '대체 장소 적용' }));
    expect(apply).toHaveBeenCalledExactlyOnceWith('trip', { optionId: 'REPLACE:b1:x' });
    expect(input.onChange).toHaveBeenCalledWith(expect.any(Function), expect.stringContaining(`용두산 공원 대신 ${placeSummaries.huinnyeoul.name}`));
  });

  it('그대로 가기는 일정을 바꾸지 않고 시트만 닫는다', async () => {
    vi.spyOn(tripsApi, 'getPlanB').mockResolvedValue(response);
    const apply = vi.spyOn(tripsApi, 'applyPlanB');
    const input = props();
    render(<PlanBSheet {...input} />);
    await userEvent.click(await screen.findByRole('button', { name: '그대로 가기' }));
    expect(apply).not.toHaveBeenCalled();
    expect(input.onChange).not.toHaveBeenCalled();
    expect(input.onClose).toHaveBeenCalled();
  });

  it('조건이 아니면 바꿀 필요가 없다고 알린다', async () => {
    vi.spyOn(tripsApi, 'getPlanB').mockResolvedValue({ blockId: 'b1', trigger: null, crowd: null, options: [] });
    render(<PlanBSheet {...props()} />);
    expect(await screen.findByText(/지금은 바꿀 필요가 없어요/)).toBeInTheDocument();
  });

  it('적용이 409 로 실패하면 시트 안에 오류를 보이고 3안을 다시 받는다', async () => {
    const get = vi.spyOn(tripsApi, 'getPlanB').mockResolvedValue({ ...response, estimated: true });
    const message = '일정이 바뀌어 이 안을 적용할 수 없어요. 플랜 B를 다시 불러 주세요.';
    vi.spyOn(tripsApi, 'applyPlanB').mockRejectedValue(new ApiError({ id: 'ERR-001', status: 409, message }));
    const input = props();
    render(<PlanBSheet {...input} />);
    expect(await screen.findByText(/이동 \+3분\(추정\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '대체 장소 적용' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(get).toHaveBeenCalledTimes(2);
    expect(input.onClose).not.toHaveBeenCalled();
  });
});
