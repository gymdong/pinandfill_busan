import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTime, formatDuration } from '@/utils/format';

describe('formatDuration', () => {
  it.each([
    [40, '40분'],
    [60, '1시간'],
    [90, '1시간 30분'],
  ])('%i분은 %s이다', (minutes, label) => {
    expect(formatDuration(minutes)).toBe(label);
  });
});

describe('formatDate', () => {
  it('요일을 붙인다', () => {
    expect(formatDate('2026-10-17')).toBe('10월 17일 (토)');
  });
});

describe('formatDateTime', () => {
  it('UTC 일시를 한국 시각으로 바꿔 요일과 24시간제 시각을 붙인다', () => {
    expect(formatDateTime('2026-11-26T05:00:00Z')).toBe('11월 26일 (목) 14:00');
  });

  it('KST 자정을 넘는 UTC 일시는 다음 날로 표시한다', () => {
    expect(formatDateTime('2026-11-26T15:30:00Z')).toBe('11월 27일 (금) 00:30');
  });

  it('오프셋이 붙은 일시는 그 시각 그대로 한국 시각으로 표시한다', () => {
    expect(formatDateTime('2026-10-17T05:00:00+09:00')).toBe('10월 17일 (토) 05:00');
  });
});
