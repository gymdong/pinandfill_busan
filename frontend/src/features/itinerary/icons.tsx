/** 시안(UI-02·UI-06)에 쓰인 선 아이콘. 장식용이므로 이름은 감싸는 버튼·링크가 갖는다. */
const base = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
} as const;

export function BackIcon() {
  return <svg {...base}><path d="M15 18l-6-6 6-6" /></svg>;
}

export function LockIcon() {
  return <svg {...base} width={16} height={16}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>;
}

export function MapIcon() {
  return <svg {...base}><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2z" /><path d="M9 4v14M15 6v14" /></svg>;
}

export function UndoIcon() {
  return <svg {...base}><path d="M9 14L4 9l5-5" /><path d="M4 9h10a6 6 0 0 1 0 12h-3" /></svg>;
}

export function PlusIcon() {
  return <svg {...base} width={16} height={16}><path d="M12 5v14M5 12h14" /></svg>;
}

export function AlertIcon() {
  return <svg {...base} width={18} height={18}><path d="M12 3l9 16H3L12 3z" /><path d="M12 10v4M12 17h.01" /></svg>;
}
