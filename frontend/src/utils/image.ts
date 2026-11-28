/**
 * 업로드 전에 사진을 다시 그려 줄인다(FR-012, NFR-006).
 * - 긴 변을 `maxSide` 이하로 줄여 전송량을 낮춘다(분석에 충분한 크기).
 * - 캔버스로 다시 그리면 촬영 위치(GPS) 등 EXIF 메타데이터가 빠진다. 원본 파일은 보내지 않는다.
 * 줄이지 못하면 예외를 던진다(원본을 대신 보내지 않는다).
 */
export async function shrinkPhoto(file: File, maxSide = 1568, quality = 0.85): Promise<File> {
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('canvas unavailable');
    context.drawImage(bitmap, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
    if (!blob) throw new Error('encode failed');
    return new File([blob], 'photo.jpg', { type: 'image/jpeg' });
  } finally {
    bitmap.close();
  }
}
