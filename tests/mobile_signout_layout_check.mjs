import { readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const index = readFileSync('static/index.html', 'utf8');
const themeCss = readFileSync('static/theme-v2.css', 'utf8');
const themeJs = readFileSync('static/theme-v2.js', 'utf8');
const finalReview = readFileSync('static/final-review.js', 'utf8');

const indexStyles = [...index.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].map(match => match[1]).join('\n');
const finalReviewStyle = finalReview.match(/style\.textContent\s*=\s*`([\s\S]*?)`;\s*document\.head\.appendChild\(style\)/)?.[1];
if (!finalReviewStyle) throw new Error('Could not extract the live Final Review view-selector CSS');

for (const marker of [
  "await fetch('/api/auth/logout', {method:'POST', credentials:'same-origin'})",
  "mobileSignout.className = 'ghost mobile-signout'",
  'mobileSignout.onclick = logoutSession',
]) {
  if (!themeJs.includes(marker)) throw new Error(`Cookie-backed mobile logout contract changed: ${marker}`);
}

// There are currently no PWA-only layout branches for this header. At an equal content
// viewport width, installed standalone mode therefore exercises the same CSS geometry.
const layoutSource = `${indexStyles}\n${themeCss}\n${finalReviewStyle}`;
if (/display-mode\s*:/i.test(layoutSource) || /navigator\.standalone/i.test(layoutSource)) {
  throw new Error('PWA-specific layout rules now exist; add a true standalone-mode case before accepting this check');
}

const browser = await chromium.launch({ headless: true });

function fixture() {
  return `<!doctype html>
  <html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
  <body>
    <div class="app">
      <aside class="side">
        <div class="brand">Shortlist<span>AI</span></div>
        <div class="sidebar-account"><div class="account-row"><div class="avatar">S</div><div class="account-copy"><b>Signed in user</b><small>Recruiter workspace</small></div><button class="signout" type="button">↗</button></div></div>
      </aside>
      <main class="main">
        <div class="mobile-header">
          <div class="brand"><span class="brand-word">Shortlist</span><span class="brand-ai">AI</span></div>
          <button class="ghost mobile-signout" type="button" aria-label="Sign out">Sign out</button>
        </div>
      </main>
    </div>
    <div id="frViewModeControl" class="fr-view-switch" role="group" aria-label="App view mode">
      <button type="button" data-view="mobile"><span>▯</span>Mobile View</button>
      <button type="button" data-view="desktop"><span>▣</span>Desktop View</button>
    </div>
    <div id="frViewModeStatus" class="fr-view-switch-status">Mobile View active</div>
  </body></html>`;
}

function overlaps(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

async function newPage(width, height = 844) {
  const context = await browser.newContext({
    viewport: { width, height },
    isMobile: width <= 420,
    hasTouch: width <= 420,
    deviceScaleFactor: width <= 420 ? 2 : 1,
    userAgent: width <= 420
      ? 'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36'
      : undefined,
  });
  const page = await context.newPage();
  await page.setContent(fixture());
  await page.addStyleTag({ content: indexStyles });
  await page.addStyleTag({ content: themeCss });
  await page.addStyleTag({ content: finalReviewStyle });
  return { context, page };
}

async function geometry(page) {
  return page.evaluate(() => {
    const box = selector => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
        width: rect.width, height: rect.height,
        display: style.display, visibility: style.visibility,
      };
    };
    return {
      viewport: { width: innerWidth, height: innerHeight },
      header: box('.mobile-header'),
      signout: box('.mobile-signout'),
      switcher: box('#frViewModeControl'),
      sidebar: box('.sidebar-account'),
    };
  });
}

for (const width of [360, 390, 412, 420]) {
  const { context, page } = await newPage(width);
  const g = await geometry(page);
  if (!g.header || g.header.display === 'none') throw new Error(`Mobile header hidden at ${width}px`);
  if (!g.signout || g.signout.display === 'none' || g.signout.visibility === 'hidden') throw new Error(`Sign out hidden at ${width}px`);
  if (!g.switcher || g.switcher.display === 'none') throw new Error(`View selector hidden at ${width}px`);
  if (overlaps(g.signout, g.switcher)) {
    throw new Error(`Sign out overlaps view selector at ${width}px: ${JSON.stringify({ signout: g.signout, switcher: g.switcher })}`);
  }
  if (g.signout.left < 0 || g.signout.right > g.viewport.width) throw new Error(`Sign out escapes viewport at ${width}px`);
  console.log(`mobile-chrome ${width}px PASS`, { signout: g.signout, switcher: g.switcher });
  await context.close();
}

// Force-desktop on a narrow viewport must suppress the mobile-only sign-out control and
// restore the sidebar account/logout area.
{
  const { context, page } = await newPage(390);
  await page.evaluate(() => document.body.classList.add('force-desktop'));
  const g = await geometry(page);
  if (g.signout?.display !== 'none') throw new Error(`force-desktop still shows mobile Sign out: ${JSON.stringify(g.signout)}`);
  if (!g.sidebar || g.sidebar.display === 'none') throw new Error('force-desktop did not restore sidebar account/logout');
  console.log('force-desktop 390px PASS');
  await context.close();
}

// Normal desktop must not surface the mobile-only header/sign-out control.
{
  const { context, page } = await newPage(1440, 900);
  const g = await geometry(page);
  if (g.header?.display !== 'none') throw new Error(`Desktop unexpectedly shows mobile header: ${JSON.stringify(g.header)}`);
  if (g.signout?.display !== 'none') throw new Error(`Desktop unexpectedly shows mobile Sign out: ${JSON.stringify(g.signout)}`);
  if (!g.sidebar || g.sidebar.display === 'none') throw new Error('Desktop sidebar account/logout is hidden');
  console.log('desktop 1440px PASS');
  await context.close();
}

await browser.close();
console.log('Mobile Sign out responsive layout verification passed');
