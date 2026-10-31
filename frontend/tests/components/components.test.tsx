import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Badge, BottomSheet, Button, Chip, ErrorState, ToastProvider, useToast } from '@/components';

describe('Badge', () => {
  it.each([
    ['detail', '상세 정보 있음'],
    ['basic', '기본 정보만'],
    ['needsCheck', '확인 필요'],
    ['estimated', '추정'],
    ['expected', '예상'],
  ] as const)('%s 배지의 문구를 표시한다', (kind, label) => {
    render(<Badge kind={kind} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('문구를 구체화할 수 있다', () => {
    render(<Badge kind="needsCheck" label="영업시간 확인 필요" />);
    expect(screen.getByText('영업시간 확인 필요')).toBeInTheDocument();
  });
});

describe('Button', () => {
  it('폼 제출을 막기 위해 기본 type이 button이다', () => {
    render(<Button>확인</Button>);
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button');
  });

  it('로딩 중에는 누를 수 없다', async () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>확인</Button>);
    await userEvent.click(screen.getByRole('button'));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('Chip', () => {
  it('선택 상태를 색 외의 방식으로도 전달한다', () => {
    render(<Chip selected>바다 전망</Chip>);
    const chip = screen.getByRole('button', { name: /바다 전망/ });
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(chip).toHaveTextContent('✓');
  });
});

describe('BottomSheet', () => {
  it('닫기 버튼과 바깥 영역을 누르면 닫기를 요청한다', async () => {
    const onClose = vi.fn();
    render(
      <BottomSheet open onClose={onClose} title="가는 길에 들를 곳">
        내용
      </BottomSheet>,
    );
    const dialog = screen.getByRole('dialog', { hidden: true });

    await userEvent.click(screen.getByRole('button', { name: '닫기', hidden: true }));
    expect(onClose).toHaveBeenCalledTimes(1);

    await userEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(2);

    await userEvent.click(screen.getByText('내용'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('닫히면 본문 스크롤 잠금을 푼다', () => {
    const { rerender } = render(
      <BottomSheet open onClose={() => {}} title="시트">
        내용
      </BottomSheet>,
    );
    expect(document.body.style.overflow).toBe('hidden');
    rerender(
      <BottomSheet open={false} onClose={() => {}} title="시트">
        내용
      </BottomSheet>,
    );
    expect(document.body.style.overflow).toBe('');
  });
});

describe('ErrorState', () => {
  it('재시도를 실행한다', async () => {
    const onRetry = vi.fn();
    render(<ErrorState message="실패" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('지정한 행동이 재시도를 대신한다', () => {
    render(<ErrorState message="실패" onRetry={() => {}} action={<a href="/">지도에서 직접 고르기</a>} />);
    expect(screen.getByRole('link', { name: '지도에서 직접 고르기' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '다시 시도' })).not.toBeInTheDocument();
  });
});

describe('Toast', () => {
  function Trigger() {
    const { showToast } = useToast();
    return <button onClick={() => showToast('담았어요')}>열기</button>;
  }

  it('메시지를 보여 주고 시간이 지나면 지운다', () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    act(() => screen.getByRole('button').click());
    expect(screen.getByText('담았어요')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(3500);
    });
    expect(screen.queryByText('담았어요')).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});
