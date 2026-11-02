const STORAGE_KEY = 'pinandfill.sessionKey';

/** 저장소를 쓸 수 없는 환경(사생활 보호 모드 등)을 위한 메모리 값 */
let memoryKey: string | null = null;

export function getSessionKey(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? memoryKey;
  } catch {
    return memoryKey;
  }
}

export function setSessionKey(key: string): void {
  memoryKey = key;
  try {
    window.localStorage.setItem(STORAGE_KEY, key);
  } catch {
    // 메모리 값으로 이어 간다.
  }
}

export function clearSessionKey(): void {
  memoryKey = null;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 지울 저장소가 없으면 할 일이 없다.
  }
}
