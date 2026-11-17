import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { recommendApi, toApiError } from '@/api';
import { paths } from '@/app/paths';
import { Banner, Button, Chip, LoadingState } from '@/components';
import { CrowdBadge } from '@/features/crowd';
import { pinnedKey, useTripDraft, type PinnedPlace } from '@/store/tripDraft';
import type { IsoDate, MoodPlace, ThemeTag } from '@/types/api';
import { formatDate } from '@/utils/format';
import styles from './MoodSearchPage.module.css';

type Status = 'idle' | 'interpreting' | 'recommending' | 'done' | 'error';

/** 여행 날짜가 정해져 있으면 그날, 아니면 오늘을 혼잡 기준일로 쓴다. */
function referenceDate(start: IsoDate | undefined): IsoDate {
  if (start && /^\d{4}-\d{2}-\d{2}$/.test(start)) return start;
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function toPinned({ place }: MoodPlace): PinnedPlace {
  return { kind: 'PUBLIC', placeId: place.id, name: place.name, coords: { lat: place.lat, lng: place.lng } };
}

/**
 * UI-08 분위기로 찾기(FR-015, FR-014).
 * SD-03 순서대로 문장을 태그로 해석한 뒤(API-013 text), 고른 태그로 추천을 받는다(API-013 tags).
 * 추천은 서버가 공공 DB 장소에서만 고르며, 화면은 받은 근거 문장과 출처를 그대로 보여 준다.
 */
export default function MoodSearchPage() {
  const navigate = useNavigate();
  const { conditions, pinned, addPinned, removePinned } = useTripDraft();
  const date = referenceDate(conditions.dates?.start);

  const [text, setText] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState<string | null>(null);
  const [tags, setTags] = useState<ThemeTag[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [avoid, setAvoid] = useState<string[]>([]);
  const [avoidOn, setAvoidOn] = useState<string[]>([]);
  const [places, setPlaces] = useState<MoodPlace[]>([]);
  const [pickedHere, setPickedHere] = useState<string[]>([]);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  function begin(next: Status): AbortSignal {
    controller.current?.abort();
    controller.current = new AbortController();
    setStatus(next);
    setMessage(null);
    return controller.current.signal;
  }

  async function recommend(tagCodes: string[], avoidList: string[]) {
    if (tagCodes.length === 0) {
      controller.current?.abort();
      setPlaces([]);
      setStatus('done');
      return;
    }
    const signal = begin('recommending');
    try {
      const response = await recommendApi.mood({ tags: tagCodes, avoid: avoidList, date }, { signal });
      if (signal.aborted) return;
      setPlaces(response.places);
      setStatus('done');
    } catch (error) {
      if (signal.aborted) return;
      setMessage(toApiError(error).message);
      setStatus('error');
    }
  }

  async function interpret(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    const signal = begin('interpreting');
    try {
      // AI 해석은 오래 걸릴 수 있어 시간 제한을 늘린다.
      const response = await recommendApi.mood({ text: value, date }, { signal, timeoutMs: 30_000 });
      if (signal.aborted) return;
      const codes = response.tags.map((tag) => tag.code);
      setTags(response.tags);
      setSelected(codes);
      setAvoid(response.avoid);
      setAvoidOn(response.avoid);
      setPlaces([]);
      await recommend(codes, response.avoid);
    } catch (error) {
      if (signal.aborted) return;
      setMessage(toApiError(error).message);
      setStatus('error');
    }
  }

  function toggleTag(code: string) {
    const next = selected.includes(code) ? selected.filter((item) => item !== code) : [...selected, code];
    setSelected(next);
    void recommend(next, avoidOn);
  }

  function toggleAvoid(item: string) {
    const next = avoidOn.includes(item) ? avoidOn.filter((value) => value !== item) : [...avoidOn, item];
    setAvoidOn(next);
    void recommend(selected, next);
  }

  function togglePin(item: MoodPlace) {
    const place = toPinned(item);
    const key = pinnedKey(place);
    if (pinned.some((entry) => pinnedKey(entry) === key)) {
      removePinned(key);
      setPickedHere((keys) => keys.filter((value) => value !== key));
    } else {
      addPinned(place);
      setPickedHere((keys) => [...keys, key]);
    }
  }

  const labelOf = (code: string) => tags.find((tag) => tag.code === code)?.label ?? code;
  const interpreted = tags.length > 0 || avoid.length > 0;
  const busy = status === 'interpreting' || status === 'recommending';

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <button type="button" className={styles.back} aria-label="뒤로 가기" onClick={() => navigate(paths.tripStart())}>
          <span aria-hidden="true">‹</span>
        </button>
        <h1 className={styles.title}>분위기로 찾기</h1>
      </header>

      <form className={styles.form} onSubmit={interpret}>
        <input
          className={styles.input}
          aria-label="원하는 분위기"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="예: 조용한 바다 감성, 사람 적은 골목"
          maxLength={200}
          autoComplete="off"
        />
        <Button type="submit" variant="outline" disabled={!text.trim()} loading={status === 'interpreting'}>
          찾기
        </Button>
      </form>

      {interpreted && (
        <div className={styles.chips} role="group" aria-label="해석된 조건">
          {tags.map((tag) => (
            <Chip key={tag.code} selected={selected.includes(tag.code)} onClick={() => toggleTag(tag.code)}>
              {tag.label}
            </Chip>
          ))}
          {avoid.map((item) => (
            <Chip key={`avoid-${item}`} selected={avoidOn.includes(item)} onClick={() => toggleAvoid(item)}>
              {item}
            </Chip>
          ))}
        </div>
      )}

      {busy && <LoadingState message={status === 'interpreting' ? '문장을 해석하는 중이에요' : '어울리는 곳을 찾는 중이에요'} />}

      {status === 'error' && (
        <Banner tone="warn" title="추천을 불러오지 못했어요">
          {message} 장소 이름을 안다면 여행 시작 화면에서 검색해 담을 수 있어요.
        </Banner>
      )}

      {status === 'done' && tags.length === 0 && (
        <Banner tone="warn">문장에서 분위기를 읽지 못했어요. ‘바다’, ‘골목’, ‘산책’처럼 다른 표현으로 다시 적어 주세요.</Banner>
      )}
      {status === 'done' && tags.length > 0 && selected.length === 0 && (
        <Banner>태그를 하나 이상 골라 주세요.</Banner>
      )}
      {status === 'done' && selected.length > 0 && places.length === 0 && (
        <Banner tone="warn">어울리는 곳을 찾지 못했어요. 태그를 직접 골라 보세요.</Banner>
      )}

      {status === 'done' && places.length > 0 && (
        <>
          <p className={styles.basis}>{formatDate(date)} 기준 예상 혼잡을 함께 보여 드려요</p>
          <ul className={styles.results} aria-label="추천 장소">
            {places.map((item) => {
              const isPinned = pinned.some((entry) => pinnedKey(entry) === pinnedKey(toPinned(item)));
              return (
                <li key={item.place.id} className={styles.card}>
                  {item.photo ? (
                    <figure className={styles.photo}>
                      <img src={item.photo.url} alt={`${item.place.name} 사진`} />
                      <figcaption>
                        {item.photo.sourceOrg} · {item.photo.licenseType ?? '저작권 유형 확인 필요'}
                      </figcaption>
                    </figure>
                  ) : (
                    <div className={`${styles.photo} ${styles.noPhoto}`}>사진 없음</div>
                  )}
                  <div className={styles.body}>
                    <div className={styles.info}>
                      <h2 className={styles.name}>{item.place.name}</h2>
                      <p className={styles.evidence}>
                        {item.evidence.matchedTags.map(labelOf).join(' · ')}
                        {item.evidence.excerpt ? ` — “${item.evidence.excerpt}”` : ' — 근거 문장 정보 없음'}
                      </p>
                      <CrowdBadge grade={item.crowd?.grade ?? null} confidence={item.crowd?.confidence} />
                    </div>
                    <Button
                      variant={isPinned ? 'outline' : 'accent'}
                      aria-pressed={isPinned}
                      aria-label={`${item.place.name} ${isPinned ? '빼기' : '담기'}`}
                      onClick={() => togglePin(item)}
                    >
                      {isPinned ? '✓ 담김' : '담기'}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <footer className={styles.footer}>
        <p className={styles.footerNote}>공공 DB에 있는 장소에서만 골랐어요 · 따옴표 문장은 장소 설명에서 맞은 부분</p>
        <Button block onClick={() => navigate(paths.tripStart())}>
          {pickedHere.length > 0 ? `${pickedHere.length}곳 담고 돌아가기` : '돌아가기'}
        </Button>
      </footer>
    </main>
  );
}
