/** Rebuild public brand assets from owner artwork and an unchanged project photograph. */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import sharp from "sharp";

const root = fileURLToPath(new URL("../../", import.meta.url));
const media = path.join(root, "apps/web/public/media");
const brand = path.join(media, "brand");
const fontfile = path.join(root, "apps/web/app/fonts/PlusJakartaSans-Variable.ttf");
const green = await readFile(path.join(root, "apps/web/public/brand/jardines-del-encanto-refinado.svg"), "utf8");
const white = await readFile(path.join(root, "assets/campaign-drafts/brand/jardines-del-encanto-blanco.svg"));
await mkdir(brand, { recursive: true });
sharp.concurrency(2);

// Keep the exact existing emblem paths/clip, not a newly invented leaf or monogram.
const defs = green.match(/<defs>[\s\S]*?<\/defs>/)?.[0];
const emblem = green.match(/<g id="emblem"[\s\S]*?<\/g>/)?.[0];
if (!defs || !emblem) throw new Error("Approved logo emblem not found");
const mark = Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="980" height="1160" viewBox="192 52 490 580">${defs}${emblem}</svg>`);
const trimmed = await sharp(mark).trim().png().toBuffer();
for (const size of [32, 48, 96, 180, 192]) {
  const padding = Math.round(size * 0.12);
  const buffer = await sharp(trimmed)
    .resize(size - padding * 2, size - padding * 2, { fit: "contain", background: "#ffffff" })
    .extend({ top: padding, bottom: padding, left: padding, right: padding, background: "#ffffff" })
    .flatten({ background: "#ffffff" }).png().toBuffer();
  await writeFile(path.join(brand, size === 180 ? "apple-touch-icon.png" : `icon-${size}.png`), buffer);
}
await sharp(Buffer.from(green)).resize(440, 440, { fit: "contain", background: "#ffffff" })
  .extend({ top: 36, bottom: 36, left: 36, right: 36, background: "#ffffff" })
  .flatten({ background: "#ffffff" }).png().toFile(path.join(brand, "logo-512.png"));

// Multi-resolution ICO embeds lossless PNGs; no external converter is required.
const sizes = [32, 48, 96];
const icons = await Promise.all(sizes.map(size => readFile(path.join(brand, `icon-${size}.png`))));
const header = Buffer.alloc(6 + icons.length * 16);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(icons.length, 4);
let offset = header.length;
icons.forEach((png, index) => {
  const entry = 6 + index * 16;
  header[entry] = sizes[index];
  header[entry + 1] = sizes[index];
  header.writeUInt16LE(1, entry + 4);
  header.writeUInt16LE(32, entry + 6);
  header.writeUInt32LE(png.length, entry + 8);
  header.writeUInt32LE(offset, entry + 12);
  offset += png.length;
});
await writeFile(path.join(brand, "favicon.ico"), Buffer.concat([header, ...icons]));

const photo = await sharp(path.join(media, "porteria-actual-1280.webp"))
  .resize(660, 630, { fit: "cover", position: "centre" }).png().toBuffer();
const logo = await sharp(white).resize(150, 178, { fit: "contain" }).png().toBuffer();
const layers = [{ input: photo, left: 540, top: 0 }, { input: logo, left: 36, top: 24 }];
async function text(value, size, color, left, top, bold = false) {
  const input = await sharp({ text: {
    text: `<span foreground="${color}">${value}</span>`,
    font: `Plus Jakarta Sans ${bold ? "Bold " : ""}${size}`,
    fontfile, rgba: true, dpi: 72, spacing: 8,
  } }).png().toBuffer();
  layers.push({ input, left, top });
}
await text("ACACÍAS · META · COLOMBIA", 14, "#dceeaa", 36, 218, true);
await text("Más tierra.\nMás vida.", 54, "#ffffff", 36, 258, true);
await text("Lotes desde $13 millones COP", 26, "#dceeaa", 36, 416, true);
await text("7 × 14 m · 98 m²", 19, "#ffffff", 36, 465);
await text("Financiación hasta 24 meses", 17, "#ffffff", 36, 500);
await text("Consulta disponibilidad y condiciones.", 11, "#c3d0c6", 36, 536);
await text("jardinesdelencanto.site", 16, "#ffffff", 36, 579, true);
const credit = await sharp({ create: { width: 302, height: 36, channels: 4, background: "#062619e6" } }).png().toBuffer();
layers.push({ input: credit, left: 866, top: 570 });
await text("Fotografía real del proyecto", 12, "#ffffff", 884, 581);
await sharp({ create: { width: 1200, height: 630, channels: 3, background: "#062619" } })
  .composite(layers).png({ palette: true, colours: 256, compressionLevel: 9 })
  .toFile(path.join(media, "jardines-del-encanto-social-20261116.png"));
console.log("Built original-brand icons and 1200×630 social card without modifying owner sources.");
