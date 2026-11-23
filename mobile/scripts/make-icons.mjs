/**
 * Draws the app icon, the Android adaptive icon layers, the splash image and the favicon from the logo's own
 * shapes (src/components/brand/logo-paths.json), so they always match the in-app logo.
 *
 *   node scripts/make-icons.mjs
 *
 * Plain Node, no packages: a small scanline rasteriser (4x4 samples per pixel) and a PNG writer on node:zlib.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deflateSync } from 'node:zlib';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const logo = JSON.parse(readFileSync(join(root, 'src/components/brand/logo-paths.json'), 'utf8'));
const out = join(root, 'assets/images');

const GREEN = [0x2a, 0x85, 0x40];
const WHITE = [0xff, 0xff, 0xff];
const SAMPLES = 4;
const CURVE_STEPS = 24;

/** An SVG path of absolute M, L, C, Q and Z commands, as closed polygons in logo units. */
function polygons(path) {
  const tokens = path.match(/[MLCQZ]|-?\d*\.?\d+/g);
  const shapes = [];
  let points = [];
  let i = 0;
  const next = () => Number(tokens[i++]);
  while (i < tokens.length) {
    const command = tokens[i++];
    if (command === 'M') {
      points = [[next(), next()]];
      shapes.push(points);
    } else if (command === 'L') {
      points.push([next(), next()]);
    } else if (command === 'C' || command === 'Q') {
      const [x0, y0] = points[points.length - 1];
      const c = command === 'C' ? [next(), next(), next(), next()] : [next(), next()];
      const [x3, y3] = [next(), next()];
      for (let step = 1; step <= CURVE_STEPS; step += 1) {
        const t = step / CURVE_STEPS;
        const u = 1 - t;
        points.push(
          command === 'C'
            ? [
                u ** 3 * x0 + 3 * u * u * t * c[0] + 3 * u * t * t * c[2] + t ** 3 * x3,
                u ** 3 * y0 + 3 * u * u * t * c[1] + 3 * u * t * t * c[3] + t ** 3 * y3,
              ]
            : [u * u * x0 + 2 * u * t * c[0] + t * t * x3, u * u * y0 + 2 * u * t * c[1] + t * t * y3],
        );
      }
    }
  }
  return shapes;
}

/** A transparent RGBA canvas, or one filled with a colour. */
function canvas(size, background = null) {
  const pixels = new Uint8ClampedArray(size * size * 4);
  if (background) {
    for (let p = 0; p < size * size; p += 1) pixels.set([...background, 255], p * 4);
  }
  return { size, pixels };
}

/** Paint one logo shape in a colour. The logo's 48-unit box is drawn `scale` pixels per unit from (left, top). */
function fill({ size, pixels }, path, color, scale, left, top) {
  const coverage = new Float32Array(size * size);
  const weight = 1 / (SAMPLES * SAMPLES);
  const shapes = polygons(path).map((shape) => shape.map(([x, y]) => [left + x * scale, top + y * scale]));
  for (let row = 0; row < size * SAMPLES; row += 1) {
    const y = (row + 0.5) / SAMPLES;
    const crossings = [];
    for (const shape of shapes) {
      for (let k = 0; k < shape.length; k += 1) {
        const [x1, y1] = shape[k];
        const [x2, y2] = shape[(k + 1) % shape.length];
        if (y1 <= y !== y2 <= y) crossings.push(x1 + ((y - y1) / (y2 - y1)) * (x2 - x1));
      }
    }
    crossings.sort((a, b) => a - b);
    for (let k = 0; k + 1 < crossings.length; k += 2) {
      const from = Math.max(0, Math.ceil(crossings[k] * SAMPLES - 0.5));
      const to = Math.min(size * SAMPLES - 1, Math.floor(crossings[k + 1] * SAMPLES - 0.5));
      for (let column = from; column <= to; column += 1) {
        coverage[Math.floor(row / SAMPLES) * size + Math.floor(column / SAMPLES)] += weight;
      }
    }
  }
  for (let p = 0; p < size * size; p += 1) {
    const alpha = Math.min(1, coverage[p]);
    if (alpha === 0) continue;
    const under = pixels[p * 4 + 3] / 255;
    const total = alpha + under * (1 - alpha);
    for (let channel = 0; channel < 3; channel += 1) {
      pixels[p * 4 + channel] = (color[channel] * alpha + pixels[p * 4 + channel] * under * (1 - alpha)) / total;
    }
    pixels[p * 4 + 3] = total * 255;
  }
}

/** Erase a shape from the canvas (for the one-colour icon, where the house is a hole in the pin). */
function cut({ size, pixels }, path, scale, left, top) {
  const mask = canvas(size);
  fill(mask, path, WHITE, scale, left, top);
  for (let p = 0; p < size * size; p += 1) {
    pixels[p * 4 + 3] = (pixels[p * 4 + 3] * (255 - mask.pixels[p * 4 + 3])) / 255;
  }
}

/** The mark, `share` of the canvas tall, centred. `pin` and `house` are colours; a null house is cut out. */
function drawMark(target, share, pin, house) {
  const scale = (target.size * share) / logo.viewBox;
  const left = (target.size - logo.viewBox * scale) / 2;
  const top = left;
  fill(target, logo.pin, pin, scale, left, top);
  if (house) {
    fill(target, logo.house, house, scale, left, top);
    fill(target, logo.leaf, pin, scale, left, top);
    fill(target, logo.midrib, house, scale, left, top);
  } else {
    cut(target, logo.house, scale, left, top);
    fill(target, logo.leaf, pin, scale, left, top);
    cut(target, logo.midrib, scale, left, top);
  }
  return target;
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function chunk(type, data) {
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  let crc = 0xffffffff;
  for (const byte of body) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const check = Buffer.alloc(4);
  check.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
  return Buffer.concat([length, body, check]);
}

function writePng(name, { size, pixels }) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header.set([8, 6, 0, 0, 0], 8); // 8 bits per channel, RGBA
  const rows = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    rows.set(pixels.subarray(y * size * 4, (y + 1) * size * 4), y * (size * 4 + 1) + 1); // filter byte 0, then the row
  }
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(rows, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
  writeFileSync(join(out, name), png);
  console.log(`${name}  ${size}x${size}  ${(png.length / 1024).toFixed(1)} KB`);
}

// The app icon: a white pin on leaf green. Android draws its own shape around the adaptive layers, so there the
// mark stays inside the middle two thirds, which is never cropped.
writePng('icon.png', drawMark(canvas(1024, GREEN), 0.7, WHITE, GREEN));
writePng('android-icon-foreground.png', drawMark(canvas(1024), 0.5, WHITE, GREEN));
writePng('android-icon-monochrome.png', drawMark(canvas(1024), 0.5, WHITE, null));
writePng('splash-icon.png', drawMark(canvas(512), 0.94, GREEN, WHITE));
writePng('favicon.png', drawMark(canvas(96), 0.96, GREEN, WHITE));
