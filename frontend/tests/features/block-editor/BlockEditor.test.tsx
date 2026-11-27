import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { tripsApi } from '@/api';
import { schedule } from '@/api/mock/fixtures/schedule';
import { BlockEditor } from '@/features/block-editor/BlockEditor';

const blocks = schedule.days[0]!.blocks;
const fixed = blocks.find((block) => block.isFixed)!;
const flexible = { ...fixed, id: 'flex', isFixed: false, fixedStart: null, fixedEnd: null };

describe('BlockEditor 장소 고치기', () => {
  it('고정 장소는 순서 입력이 없고, 빼기는 한 번 더 확인한다(원칙 1)', async () => {
    const remove = vi.spyOn(tripsApi, 'deleteBlock').mockResolvedValue({ schedule, violations: [] });
    const onChange = vi.fn(async (action: () => Promise<unknown>) => { await action(); });
    render(<BlockEditor tripId="t1" block={fixed} disabled={false} onChange={onChange} />);
    expect(screen.queryByRole('button', { name: '순서 변경' })).not.toBeInTheDocument();
    expect(screen.getByText('고정한 장소라 순서와 시각은 바뀌지 않아요.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '일정에서 빼기' }));
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('button', { name: '고정 장소지만 빼기' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '일정에서 빼기' }));
    await userEvent.click(screen.getByRole('button', { name: '고정 장소지만 빼기' }));
    expect(remove).toHaveBeenCalledWith('t1', fixed.id);
  });

  it('고정하지 않은 장소는 순서를 바꾸고 바로 뺄 수 있다', async () => {
    const remove = vi.spyOn(tripsApi, 'deleteBlock').mockResolvedValue({ schedule, violations: [] });
    render(<BlockEditor tripId="t1" block={flexible} disabled={false} onChange={async (action) => { await action(); }} />);
    expect(screen.getByRole('button', { name: '순서 변경' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '일정에서 빼기' }));
    expect(remove).toHaveBeenCalledWith('t1', 'flex');
  });
});
