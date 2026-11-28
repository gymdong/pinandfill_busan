import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { placesApi } from '@/api';
import { placeSummaries } from '@/api/mock/fixtures/places';
import PhotoSearchPage from '@/pages/photo-search';
import * as image from '@/utils/image';

const shrunk = new File(['jpeg'], 'photo.jpg', { type: 'image/jpeg' });

beforeEach(() => {
  vi.spyOn(image, 'shrinkPhoto').mockResolvedValue(shrunk);
  URL.createObjectURL = vi.fn(() => 'blob:preview');
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

async function choose() {
  render(<MemoryRouter><PhotoSearchPage /></MemoryRouter>);
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(['raw'], 'IMG_0001.HEIC.jpg', { type: 'image/jpeg' }));
}

describe('사진으로 찾기(FR-012)', () => {
  it('줄인 사진만 보내고 후보를 확신도와 함께 보여 주며 담을 수 있다', async () => {
    const search = vi.spyOn(placesApi, 'photoSearch').mockResolvedValue({
      candidates: [{ place: placeSummaries.taejongdae, confidence: 0.86 }], notFound: false,
    });
    await choose();
    expect(await screen.findByRole('heading', { name: placeSummaries.taejongdae.name })).toBeInTheDocument();
    expect(search).toHaveBeenCalledWith(shrunk, { signal: expect.any(AbortSignal), timeoutMs: 45_000 });
    expect(screen.getByText(/확신도 86%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: `${placeSummaries.taejongdae.name} 담기` }));
    expect(screen.getByRole('button', { name: `${placeSummaries.taejongdae.name} 빼기` })).toBeInTheDocument();
  });

  it('확신이 낮으면 찾지 못했다고 하고 이름 검색으로 안내한다', async () => {
    vi.spyOn(placesApi, 'photoSearch').mockResolvedValue({ candidates: [], notFound: true });
    await choose();
    expect(await screen.findByText('사진으로는 찾지 못했어요')).toBeInTheDocument();
  });

  it('사진을 줄이지 못하면 원본을 보내지 않는다', async () => {
    vi.spyOn(image, 'shrinkPhoto').mockRejectedValue(new Error('decode'));
    const search = vi.spyOn(placesApi, 'photoSearch');
    await choose();
    expect(await screen.findByText(/이 사진은 읽을 수 없어요/)).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });
});
