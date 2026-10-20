import {createHash,randomUUID} from 'node:crypto';
import {mkdir,writeFile,rename} from 'node:fs/promises';
import {join} from 'node:path';
import sharp,{type Metadata} from 'sharp';
import {HttpError} from './errors.js';
export async function storeVisualAsset(
  folder: string,
  input: Buffer,
  requireAlpha = false,
  requireOpaque = false,
  canvas?: {width:number;height:number},
  options: {preserveOriginal?:boolean} = {},
) {
  if (!input.length || input.length > 24 * 1024 * 1024)
    throw new HttpError(413, "Изображение превышает 24 МБ", "visual_size");
  let image: Buffer, info: Metadata;
  try {
    const source = sharp(input, {
      limitInputPixels: 24_000_000,
      animated: false,
    });
    info = await source.metadata();
    if (
      !["png", "jpeg", "webp"].includes(info.format || "") ||
      !info.width ||
      !info.height
    )
      throw new Error("format");
    const stats = await source.stats();
    if (
      requireAlpha &&
      (!info.hasAlpha || stats.isOpaque || stats.channels.at(-1)?.max === 0)
    )
      throw new HttpError(
        422,
        "Модель вернула изображение без прозрачного фона. Можно повторить только эту картинку.",
        "visual_alpha",
      );
    if (requireOpaque && !stats.isOpaque)
      throw new HttpError(
        422,
        "За текстом требуется непрозрачное изображение. Загрузите JPEG или PNG без прозрачности.",
        "visual_backdrop_alpha",
      );
    if (options.preserveOriginal && (canvas || !['png','jpeg'].includes(info.format!) || (info.pages??1)>1))
      throw new HttpError(400,"Исходный рисунок должен быть отдельным PNG или JPEG без изменения холста.","visual_original_format");
    // Validate the provider's original alpha before resizing. An opaque text
    // backdrop must still fill the target canvas after an aspect-ratio change.
    const normalized=canvas?await sharp(input).resize({...canvas,fit:requireOpaque?'cover':'contain',background:{r:0,g:0,b:0,alpha:0}}).png().toBuffer():input;
    image = options.preserveOriginal ? input : await sharp(normalized, { limitInputPixels: 24_000_000 }).rotate()
      .resize({
        width: 2048,
        height: 2048,
        fit: "inside",
        withoutEnlargement: true,
      })
      .png()
      .toBuffer();
  } catch (e) {
    if (e instanceof HttpError) throw e;
    throw new HttpError(
      400,
      "Не удалось прочитать PNG, JPEG или WebP",
      "visual_format",
    );
  }
  const extension=options.preserveOriginal&&info.format==='jpeg'?'.jpg':'.png';
  const name = createHash("sha256").update(image).digest("hex") + extension;
  const directory = join(folder, "visual-assets");
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temp = join(directory, `${randomUUID()}.tmp`);
  await writeFile(temp, image, { mode: 0o600 });
  await rename(temp, join(directory, name));
  return name;
}
