import { useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toApiError, tripsApi } from '@/api';
import { paths } from '@/app/paths';
import { Badge, Banner, Button } from '@/components';
import { PlaceSearch, pinnedBadgeKind, toPinnedPlace } from '@/features/place-search';
import {
  DEFAULT_CONDITIONS,
  MODE_OPTIONS,
  dayDate,
  tripDays,
  tripLengthLabel,
  validateConditions,
} from '@/features/trip-start/conditions';
import {
  CourseIncompleteError,
  createCourse,
  validatePlans,
  type CourseProgress,
} from '@/features/trip-start/createCourse';
import { pinnedKey, planOf, useTripDraft, type PinnedPlace, type PinnedPlan } from '@/store/tripDraft';
import { formatDate } from '@/utils/format';
import styles from './TripStartPage.module.css';

type InterpretStatus = 'idle' | 'loading' | 'done' | 'needsForm';

/** 여행과 장소는 저장됐지만 일정 계산이 실패한 상태. 입력이 그대로일 때만 보여 준다. */
interface PendingTrip {
  tripId: string;
  message: string;
  inputKey: string;
}

const MAP_HINT = '찾는 곳이 없으면 코스를 만든 뒤 지도 보기에서 직접 고를 수 있어요.';

/** UI-01 여행 시작: 여행 조건 입력(FR-002)과 꼭 갈 곳 담기(FR-001) */
export default function TripStartPage() {
  const navigate = useNavigate();
  const { conditions: draft, pinned, plans, setConditions, addPinned, removePinned, setPlan, reset } = useTripDraft();
  const conditions = { ...DEFAULT_CONDITIONS, ...draft };
  const days = tripDays(conditions.dates);
  const dayCount = days ?? 1;

  const [text, setText] = useState('');
  const [interpretStatus, setInterpretStatus] = useState<InterpretStatus>('idle');
  const [showErrors, setShowErrors] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingTrip | null>(null);
  const startDateRef = useRef<HTMLInputElement>(null);
  // 장소 추가가 중간에 실패한 여행. 같은 입력으로 다시 시도하면 새 여행을 만들지 않고 이어 간다.
  const unfinished = useRef<{ progress: CourseProgress; inputKey: string } | null>(null);

  // 여행 기간을 줄이면 사라진 일차에 둔 장소는 마지막 날로 옮겨 보여 준다.
  const effectivePlans = useMemo(() => {
    const entries = pinned.map((place) => {
      const key = pinnedKey(place);
      const plan = planOf(plans, key);
      return [key, { ...plan, dayNo: Math.min(Math.max(plan.dayNo, 1), dayCount) }] as const;
    });
    return Object.fromEntries(entries) as Record<string, PinnedPlan>;
  }, [pinned, plans, dayCount]);

  const pickedKeys = useMemo(() => new Set(pinned.map(pinnedKey)), [pinned]);
  const validation = validateConditions(draft);
  const errors = showErrors && !validation.ok ? validation.errors : {};
  const planErrors = showErrors ? validatePlans(pinned, effectivePlans, dayCount) : {};
  const inputKey = JSON.stringify([draft, pinned.map(pinnedKey), effectivePlans]);
  const pendingTrip = pending?.inputKey === inputKey ? pending : null;

  async function interpret(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    setInterpretStatus('loading');
    try {
      // AI 해석은 오래 걸릴 수 있어 시간 제한을 늘린다.
      const response = await tripsApi.interpret({ text: value }, { timeoutMs: 30_000 });
      setConditions(response.conditions);
      setInterpretStatus(response.needsForm ? 'needsForm' : 'done');
      if (response.needsForm) startDateRef.current?.focus();
    } catch {
      // 해석 실패·AI 장애는 항목별 입력으로 이어 간다(FR-002, AI-REQ-05).
      setInterpretStatus('needsForm');
      startDateRef.current?.focus();
    }
  }

  function changeDates(change: { start?: string; end?: string }) {
    const start = change.start ?? conditions.dates?.start ?? '';
    let end = change.end ?? conditions.dates?.end ?? '';
    // 시작일을 종료일 뒤로 옮기면 당일 여행으로 맞춘다.
    if (change.start !== undefined && start && (!end || end < start)) end = start;
    setConditions({ dates: { start, end } });
  }

  function goToTimeline(tripId: string) {
    reset();
    navigate(paths.timeline(tripId));
  }

  async function submit() {
    setShowErrors(true);
    setSubmitError(null);
    if (!validation.ok || Object.keys(validatePlans(pinned, effectivePlans, dayCount)).length > 0) {
      setSubmitError('입력한 내용을 다시 확인해 주세요.');
      return;
    }
    setSubmitting(true);
    try {
      const resume = unfinished.current?.inputKey === inputKey ? unfinished.current.progress : undefined;
      const { tripId, scheduleError } = await createCourse(validation.value, pinned, effectivePlans, resume);
      unfinished.current = null;
      if (scheduleError) setPending({ tripId, message: scheduleError.message, inputKey });
      else goToTimeline(tripId);
    } catch (error) {
      if (error instanceof CourseIncompleteError) {
        unfinished.current = { progress: error.progress, inputKey };
        setSubmitError(`${error.apiError.message} 다시 누르면 남은 장소부터 이어서 담아요.`);
      } else {
        unfinished.current = null;
        setSubmitError(toApiError(error).message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.step}>새 여행 · 1/2 단계</p>
        <h1 className={styles.title}>
          꼭 갈 곳만 담아주세요.
          <br />
          사이 동선은 저희가 채울게요.
        </h1>
      </header>

      <section className={styles.section} aria-label="한 줄로 입력">
        <form className={styles.interpretForm} onSubmit={interpret}>
          <label htmlFor="trip-text" className="sr-only">여행 조건 한 줄 입력</label>
          <input
            id="trip-text"
            className={styles.textInput}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="예: 10/17~19 2박 3일 대중교통"
            maxLength={200}
            autoComplete="off"
          />
          <Button type="submit" variant="outline" disabled={!text.trim()} loading={interpretStatus === 'loading'}>
            {interpretStatus === 'loading' ? '해석 중' : '해석'}
          </Button>
        </form>
        {interpretStatus === 'done' && <Banner>해석한 조건을 아래에 채웠어요. 틀린 항목은 바로 고칠 수 있어요.</Banner>}
        {interpretStatus === 'needsForm' && <Banner tone="warn">문장을 해석하지 못했어요. 아래 항목을 직접 입력해 주세요.</Banner>}
      </section>

      <section className={styles.card} aria-label="여행 조건">
        <div className={styles.row}>
          <span className={styles.rowLabel}>날짜</span>
          <span className={styles.rowInputs}>
            <input
              ref={startDateRef}
              className={styles.field}
              type="date"
              aria-label="여행 시작일"
              aria-invalid={Boolean(errors.dates)}
              value={conditions.dates?.start ?? ''}
              onChange={(event) => changeDates({ start: event.target.value })}
            />
            <span aria-hidden="true">–</span>
            <input
              className={styles.field}
              type="date"
              aria-label="여행 종료일"
              aria-invalid={Boolean(errors.dates)}
              min={conditions.dates?.start || undefined}
              value={conditions.dates?.end ?? ''}
              onChange={(event) => changeDates({ end: event.target.value })}
            />
          </span>
          {days !== null && <span className={styles.rowNote}>{tripLengthLabel(days)}</span>}
          {errors.dates && <p className={styles.error} role="alert">{errors.dates}</p>}
        </div>

        <div className={styles.row}>
          <span className={styles.rowLabel}>하루 일정</span>
          <span className={styles.rowInputs}>
            <input
              className={`${styles.field} ${styles.time}`}
              type="time"
              aria-label="하루 시작 시각"
              aria-invalid={Boolean(errors.hours)}
              value={conditions.dayStart}
              onChange={(event) => setConditions({ dayStart: event.target.value })}
            />
            <span aria-hidden="true">–</span>
            <input
              className={`${styles.field} ${styles.time}`}
              type="time"
              aria-label="하루 종료 시각"
              aria-invalid={Boolean(errors.hours)}
              value={conditions.dayEnd}
              onChange={(event) => setConditions({ dayEnd: event.target.value })}
            />
          </span>
          {errors.hours && <p className={styles.error} role="alert">{errors.hours}</p>}
        </div>

        <div className={styles.row}>
          <span className={styles.rowLabel} id="trip-mode-label">이동</span>
          <span className={styles.modes} role="radiogroup" aria-labelledby="trip-mode-label">
            {MODE_OPTIONS.map(({ mode, label }) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={conditions.mode === mode}
                className={styles.mode}
                onClick={() => setConditions({ mode })}
              >
                {label}
              </button>
            ))}
          </span>
        </div>

        <details className={styles.optional}>
          <summary>동행·예산 (선택)</summary>
          <label className={styles.optionalField}>
            <span>동행</span>
            <input
              className={styles.field}
              value={conditions.companions ?? ''}
              onChange={(event) => setConditions({ companions: event.target.value })}
              placeholder="예: 친구 2명"
              maxLength={50}
            />
          </label>
          <label className={styles.optionalField}>
            <span>예산(원)</span>
            <input
              className={styles.field}
              type="number"
              inputMode="numeric"
              min={0}
              step={1000}
              aria-invalid={Boolean(errors.budget)}
              value={conditions.budget ?? ''}
              onChange={(event) => setConditions({ budget: event.target.value === '' ? undefined : Number(event.target.value) })}
            />
          </label>
          {errors.budget && <p className={styles.error} role="alert">{errors.budget}</p>}
        </details>
      </section>

      <section className={styles.section} aria-label="꼭 갈 곳">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>
            꼭 갈 곳 <span className={styles.count}>{pinned.length}</span>
          </h2>
          <span className={styles.sectionNote}>시간을 정하면 고정돼요</span>
        </div>

        {pinned.length > 0 && (
          <ul className={styles.pinnedList}>
            {pinned.map((place) => {
              const key = pinnedKey(place);
              return (
                <PinnedItem
                  key={key}
                  place={place}
                  plan={planOf(effectivePlans, key)}
                  dayCount={dayCount}
                  startDate={conditions.dates?.start}
                  error={planErrors[key]}
                  onPlan={(plan) => setPlan(key, plan)}
                  onRemove={() => removePinned(key)}
                />
              );
            })}
          </ul>
        )}

        <PlaceSearch
          pickedKeys={pickedKeys}
          onPick={(item) => addPinned(toPinnedPlace(item))}
          onUnpick={(item) => removePinned(pinnedKey(toPinnedPlace(item)))}
          fallbackHint={MAP_HINT}
        />

        <Link className={styles.moodLink} to={paths.moodSearch()}>
          <span>원하는 분위기로 찾기</span>
          <span aria-hidden="true">›</span>
        </Link>
      </section>

      <footer className={styles.footer}>
        {submitError && <Banner tone="warn">{submitError}</Banner>}
        {pendingTrip ? (
          <>
            <Banner tone="warn" title="여행은 만들었지만 일정 계산을 마치지 못했어요">{pendingTrip.message}</Banner>
            <Button block onClick={() => goToTimeline(pendingTrip.tripId)}>타임라인에서 확인하기</Button>
          </>
        ) : (
          <>
            <p className={styles.footerNote}>
              {pinned.length === 0 ? '꼭 갈 곳을 1곳 이상 담으면 코스를 만들 수 있어요' : '사이 구간의 경유지는 코스를 만든 뒤에 찾아요'}
            </p>
            <Button block disabled={pinned.length === 0} loading={submitting} onClick={submit}>
              {submitting ? '코스 만드는 중' : '코스 만들기'}
            </Button>
          </>
        )}
      </footer>
    </main>
  );
}

function PinnedItem({ place, plan, dayCount, startDate, error, onPlan, onRemove }: {
  place: PinnedPlace;
  plan: PinnedPlan;
  dayCount: number;
  startDate: string | undefined;
  error: string | undefined;
  onPlan: (plan: Partial<PinnedPlan>) => void;
  onRemove: () => void;
}) {
  return (
    <li className={styles.pinned}>
      <div className={styles.pinnedHead}>
        <span className={styles.pinnedName}>{place.name}</span>
        <Badge kind={pinnedBadgeKind(place)} />
        <button type="button" className={styles.textButton} aria-label={`${place.name} 빼기`} onClick={onRemove}>빼기</button>
      </div>
      <div className={styles.pinnedPlan}>
        {dayCount > 1 && (
          <select
            className={styles.field}
            aria-label={`${place.name} 방문 일차`}
            value={plan.dayNo}
            onChange={(event) => onPlan({ dayNo: Number(event.target.value) })}
          >
            {Array.from({ length: dayCount }, (_, index) => {
              const date = dayDate(startDate, index + 1);
              return <option key={index} value={index + 1}>{index + 1}일차{date ? ` · ${formatDate(date)}` : ''}</option>;
            })}
          </select>
        )}
        {plan.fixed ? (
          <>
            <span className={styles.rowInputs}>
              <input
                className={`${styles.field} ${styles.time}`}
                type="time"
                aria-label={`${place.name} 도착 시각`}
                aria-invalid={Boolean(error)}
                value={plan.fixed.start}
                onChange={(event) => onPlan({ fixed: { start: event.target.value, end: plan.fixed?.end ?? '' } })}
              />
              <span aria-hidden="true">–</span>
              <input
                className={`${styles.field} ${styles.time}`}
                type="time"
                aria-label={`${place.name} 출발 시각`}
                aria-invalid={Boolean(error)}
                value={plan.fixed.end}
                onChange={(event) => onPlan({ fixed: { start: plan.fixed?.start ?? '', end: event.target.value } })}
              />
            </span>
            <button type="button" className={styles.textButton} onClick={() => onPlan({ fixed: null })}>시간 빼기</button>
          </>
        ) : (
          <button type="button" className={styles.textButton} onClick={() => onPlan({ fixed: { start: '', end: '' } })}>
            시간 정하기
          </button>
        )}
      </div>
      {error && <p className={styles.error} role="alert">{error}</p>}
    </li>
  );
}
