// Regenerates the 11 iOS launch screens in launch/ (Build 292, 2026-08-01).
//
// Each file is a REAL screenshot of the app's own splash at one iPhone's exact
// pixel size, so the launch screen iOS shows from icon-tap flows seamlessly into
// the live splash. iOS matches on device-width/height/DPR EXACTLY and reads the
// files at Add-to-Home-Screen time: a size not in the table below (and in the
// <link rel="apple-touch-startup-image"> table in index.html's head) falls back
// to a plain white screen, and changes only reach a phone after the old
// home-screen icon is deleted and the app re-added.
//
// Since v292 the splash ground is the brand orange rather than the theme accent,
// so ONE set of screenshots is correct for every theme -- see the .splash comment
// in index.html. Keep the two tables in step: this list and the head's <link> list.
//
// The splash normally drops itself after 1.7-4.2s and is then removed from the
// DOM. Rather than race it, this patches document.getElementById so the splash
// IIFE's own `if(!sp) return;` fires and the splash simply never leaves.
//
// Usage:
//   python3 -m http.server 8787          # from the repo root
//   npm install puppeteer-core           # anywhere; point NODE_PATH at it
//   node tools/build_launch.js           # overwrites all 11 PNGs
//
// Requires Google Chrome, and Pillow for the final 128-colour quantize (the
// splash is flat colour plus one white silhouette, so 128 colours is visually
// lossless and takes each file from ~300 KB to ~55 KB).

const puppeteer = require('puppeteer-core');
const { execFileSync } = require('child_process');
const path = require('path');
const os = require('os');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const URL = 'http://localhost:8787/index.html';
const OUT = path.join(__dirname, '..', 'launch');

// width, height, dpr -- the CSS viewport and scale factor of each iPhone the
// head's <link> table lists. File name is width*dpr x height*dpr.
const DEVICES = [
  [375, 667, 2], [414, 736, 3], [375, 812, 3], [390, 844, 3],
  [393, 852, 3], [402, 874, 3], [414, 896, 2], [414, 896, 3],
  [428, 926, 3], [430, 932, 3], [440, 956, 3],
];

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    // Chrome prompts for the 'Chrome Safe Storage' keychain item and hangs without
    // the mock keychain; the profile goes to a temp dir so it never lands in the repo.
    args: ['--use-mock-keychain', '--user-data-dir=' + path.join(os.tmpdir(), 'wtf-launch-profile')],
  });

  for (const [w, h, dpr] of DEVICES) {
    const page = await browser.newPage();
    // Freeze the splash: the IIFE bails on a null #splash and never schedules its drop.
    await page.evaluateOnNewDocument(() => {
      const real = document.getElementById.bind(document);
      let swallowed = false;
      document.getElementById = (id) => {
        if (id === 'splash' && !swallowed) { swallowed = true; return null; }
        return real(id);
      };
    });
    await page.setViewport({ width: w, height: h, deviceScaleFactor: dpr });
    await page.goto(URL, { waitUntil: 'networkidle2' });
    await page.evaluate(() => document.fonts.ready);
    await new Promise((r) => setTimeout(r, 400));

    const file = path.join(OUT, `launch-${w * dpr}x${h * dpr}.png`);
    await page.screenshot({ path: file });
    await page.close();

    execFileSync('python3', ['-c',
      'import sys;from PIL import Image;p=sys.argv[1];' +
      'Image.open(p).convert("RGB").quantize(colors=128,method=Image.MEDIANCUT)' +
      '.save(p,optimize=True)', file]);
    console.log(path.basename(file));
  }

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
