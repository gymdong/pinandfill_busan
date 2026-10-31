import { describe, expect, it } from 'vitest';
import { formatDate, formatDuration } from '@/utils/format';

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
