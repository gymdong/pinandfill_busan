import { useCallback, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { placesApi } from '@/api';
import { paths } from '@/app/paths';
import { Badge, Button, ErrorState, LoadingState } from '@/components';
import { CrowdBadge } from '@/features/crowd';
import { DAY_LABEL, WEEK_ORDER, dayTypeOf, describeHours, hoursFor } from '@/features/place-detail/hours';
import { useApi } from '@/hooks/useApi';
import { pinnedKey, useTripDraft, type PinnedPlace } from '@/store/tripDraft';
import type { PlaceDetailResponse, PlacePhoto } from '@/types/api';
import { formatDate } from '@/utils/format';
import styles from './PlaceDetailPage.module.css';

/** UI-04 장소 상세: 영업시간 확인(FR-001), 사진과 출처·저작권(FR-014), 출처·기준일(NFR-007) */
export default function PlaceDetailPage() {
  const { placeId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const date = searchParams.get('date');
  const navigate = useNavigate();
  const load = useCallback(
    (signal: AbortSignal) => placesApi.get(placeId, date ?? undefined, { signal }),
    [placeId, date],
  );
  const { status, data, error, reload } = useApi(load);

  return (
    <main className={styles.page}>
      <button type="button" className={styles.back} aria-label="뒤로 가기" onClick={() => navigate(-1)}>
        <span aria-hidden="true">‹</span>
      </button>
      {status === 'loading' && <LoadingState message="장소 정보를 불러오는 중이에요" />}
      {status === 'error' && (
        <ErrorState
          message={error.message}
          onRetry={error.id === 'ERR-016' ? undefined : reload}
          action={error.id === 'ERR-016' ? <Button onClick={() => navigate(paths.tripStart())}>처음으로</Button> : undefined}
        />
      )}
      {status === 'success' && <PlaceDetail detail={data} date={date} />}
    </main>
  );
}

function PlaceDetail({ detail, date }: { detail: PlaceDetailResponse; date: string | null }) {
  const { place, hours, photos, crowd, sources } = detail;
  const { pinned, addPinned, removePinned } = useTripDraft();
  const asPinned: PinnedPlace = {
    kind: 'PUBLIC',
    placeId: place.id,
    name: place.name,
    coords: { lat: place.lat, lng: place.lng },
  };
  const key = pinnedKey(asPinned);
  const isPinned = pinned.some((item) => pinnedKey(item) === key);

  const dayType = dayTypeOf(date);
  const today = describeHours(hoursFor(hours, dayType));
  const weekly = WEEK_ORDER.map((type) => ({ type, item: hours.find((entry) => entry.dayType === type) })).filter(
    ({ type, item }) => type !== 'HOLIDAY' || item,
  );

  return (
    <>
      <PhotoViewer key={place.id} photos={photos} placeName={place.name} />

      <header className={styles.header}>
        <p className={styles.meta}>{[place.category, place.indoorOutdoor].join(' · ')}</p>
        <h1 className={styles.title}>{place.name}</h1>
        {place.description && <p className={styles.description}>{place.description}</p>}
      </header>

      <section className={styles.card} aria-label="운영 정보">
        <div className={styles.row}>
          <span className={styles.rowLabel}>{dayType && date ? formatDate(date) : '운영'}</span>
          {dayType ? (
            <span className={styles.rowValue}>
              {today.kind === 'open' && <span className={styles.mono}>{today.text}</span>}
              {today.kind === 'closed' && <Badge kind="needsCheck" label="이 날은 휴무예요" />}
              {today.kind === 'unknown' && <Badge kind="needsCheck" label={today.text} />}
            </span>
          ) : (
            <span className={styles.rowValue}>
              {hours.length === 0 ? <Badge kind="needsCheck" label="영업시간 확인 필요" /> : '요일별 시간을 확인하세요'}
            </span>
          )}
        </div>
        {hours.length > 0 && (
          <details className={styles.week}>
            <summary>요일별 운영시간</summary>
            <ul>
              {weekly.map(({ type, item }) => {
                const info = describeHours(item);
                return (
                  <li key={type} className={type === dayType ? styles.weekToday : undefined}>
                    <span>{DAY_LABEL[type]}</span>
                    <span className={info.kind === 'open' ? styles.mono : undefined}>{info.text}</span>
                  </li>
                );
              })}
            </ul>
          </details>
        )}
        {place.closedDaysText && (
          <div className={styles.row}>
            <span className={styles.rowLabel}>휴무</span>
            <span className={styles.rowValue}>{place.closedDaysText}</span>
          </div>
        )}
        <div className={styles.row}>
          <span className={styles.rowLabel}>예상 혼잡</span>
          <span className={styles.rowValue}>
            <CrowdBadge grade={crowd?.grade ?? null} confidence={crowd?.confidence} />
          </span>
        </div>
      </section>

      <section className={styles.sources} aria-label="출처">
        {sources.length > 0 ? (
          <ul>
            {sources.map((source) => (
              <li key={`${source.org}-${source.refDate}`}>
                장소 정보 {source.org} · {formatDate(source.refDate)} 기준
              </li>
            ))}
          </ul>
        ) : (
          <p>출처 정보 없음</p>
        )}
        {crowd?.grade && crowd.sources.length > 0 && <p>혼잡 근거 {crowd.sources.join(', ')}</p>}
      </section>

      <div className={styles.actions}>
        <Button block variant={isPinned ? 'outline' : 'primary'} onClick={() => (isPinned ? removePinned(key) : addPinned(asPinned))}>
          {isPinned ? '✓ 꼭 갈 곳에 담김 · 빼기' : '꼭 갈 곳에 담기'}
        </Button>
      </div>
    </>
  );
}

/** 대표 사진을 먼저 보여 주고 사진마다 출처와 저작권 유형을 표시한다. 없으면 다른 출처에서 가져오지 않는다(FR-014). */
function PhotoViewer({ photos, placeName }: { photos: PlacePhoto[]; placeName: string }) {
  const ordered = [...photos].sort((a, b) => Number(b.isPrimary) - Number(a.isPrimary));
  const [index, setIndex] = useState(0);
  const photo = ordered[Math.min(index, ordered.length - 1)];

  if (!photo) {
    return (
      <div className={`${styles.photo} ${styles.noPhoto}`}>
        <p>사진 없음</p>
      </div>
    );
  }
  return (
    <figure className={styles.photo}>
      <img src={photo.url} alt={`${placeName} 사진 ${index + 1}`} />
      <figcaption className={styles.credit}>
        사진 {photo.sourceOrg} · {photo.licenseType ?? '저작권 유형 확인 필요'}
      </figcaption>
      {ordered.length > 1 && (
        <div className={styles.pager}>
          <button type="button" aria-label="이전 사진" disabled={index === 0} onClick={() => setIndex(index - 1)}>
            ‹
          </button>
          <span aria-live="polite">
            {index + 1} / {ordered.length}
          </span>
          <button type="button" aria-label="다음 사진" disabled={index === ordered.length - 1} onClick={() => setIndex(index + 1)}>
            ›
          </button>
        </div>
      )}
    </figure>
  );
}
