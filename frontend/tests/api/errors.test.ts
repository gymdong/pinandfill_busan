import { describe, expect, it } from 'vitest';
import { ERROR_CATALOG } from '@/api';
import { parseErrorResponse } from '@/api/errors';

describe('ERROR_CATALOG', () => {
  it('SDD 8장의 ERR-001~017을 모두 담는다', () => {
    const expected = Array.from({ length: 17 }, (_, i) => `ERR-${String(i + 1).padStart(3, '0')}`);
    expect(Object.keys(ERROR_CATALOG)).toEqual(expected);
  });

  it('200으로 내려가는 항목은 inline으로 구분한다', () => {
    const inline = Object.entries(ERROR_CATALOG)
      .filter(([, entry]) => entry.delivery === 'inline')
      .map(([id]) => id);
    expect(inline).toEqual(expect.arrayContaining(['ERR-002', 'ERR-010', 'ERR-013']));
    expect(inline).not.toContain('ERR-003');
  });
});

describe('parseErrorResponse', () => {
  it.each([
    [400, 'ERR-001'],
    [403, 'ERR-016'],
    [409, 'ERR-009'],
    [413, 'ERR-014'],
    [422, 'ERR-015'],
    [503, 'ERR-017'],
    [500, 'UNKNOWN'],
  ])('본문이 없는 %i 응답은 %s가 된다', (status, id) => {
    expect(parseErrorResponse(status, undefined).id).toBe(id);
  });

  it('카탈로그에 없는 오류 ID는 상태 코드로 대체한다', () => {
    expect(parseErrorResponse(400, { error: { id: 'ERR-999' } }).id).toBe('ERR-001');
  });
});
