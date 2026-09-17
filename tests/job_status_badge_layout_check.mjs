import { readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const index = readFileSync('static/index.html', 'utf8');
const dashboardCss = readFileSync('static/dashboard-v2.css', 'utf8');
const themeCss = readFileSync('static/theme-v2.css', 'utf8');
const indexStyles = [...index.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].map(match => match[1]).join('\n');

const browser = await chromium.launch({ headless: true });

function fixture() {
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>
    <main class="main">
      <div class="dashv2-card">
        <h3>Active jobs</h3><div class="sub">Requirement-level pipeline snapshot.</div>
        <div class="dashv2-jobs">
          <div class="dashv2-job" data-job="1">
            <div class="dashv2-job-top">
              <div><b>Senior Python Platform Engineer with a deliberately long mobile title</b><small>Engineering • Chennai, Tamil Nadu</small></div>
              <span class="badge Strong">Open</span>
            </div>
            <div class="dashv2-job-metrics">
              <span><strong>12</strong>Sourced</span><span><strong>8</strong>Pipeline</span><span><strong>3</strong>L2 cleared</span><span><strong>1</strong>Hired</span>
            </div>
          </div>
        </div>
      </div>
    </main>
  </body></html>`;
}

async function openPage(width, height = 844) {
  const context = await browser.newContext({
    viewport: { width, height },
    isMobile: width <= 420,
    hasTouch: width <= 420,
    deviceScaleFactor: width <= 420 ? 2 : 1,
    userAgent: width <= 420 ? 'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36' : undefined,
  });
  const page = await context.newPage();
  await page.setContent(fixture());
  await page.addStyleTag({ content: indexStyles });
  await page.addStyleTag({ content: dashboardCss });
  await page.addStyleTag({ content: themeCss });
  return { context, page };
}

async function geometry(page) {
  return page.evaluate(() => {
    const rect = selector => {
      const el = document.querySelector(selector);
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return { left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height, display:s.display, minHeight:s.minHeight, alignSelf:s.alignSelf, whiteSpace:s.whiteSpace };
    };
    const metrics = [...document.querySelectorAll('.dashv2-job-metrics span')].map(el => {
      const r = el.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};
    });
    return {
      viewport: innerWidth,
      card: rect('.dashv2-job'),
      header: rect('.dashv2-job-top'),
      copy: rect('.dashv2-job-top > div'),
      badge: rect('.dashv2-job-top > .badge'),
      metrics,
      metricColumns: getComputedStyle(document.querySelector('.dashv2-job-metrics')).gridTemplateColumns,
    };
  });
}

function assertLayout(g, width, expectedMetricColumns) {
  if (g.badge.height > 30) throw new Error(`Open badge too tall at ${width}px: ${JSON.stringify(g.badge)}`);
  if (g.badge.height >= g.header.height * 0.8 && g.header.height > 36) throw new Error(`Open badge appears vertically stretched at ${width}px`);
  if (Math.abs(g.badge.top - g.header.top) > 2) throw new Error(`Open badge is not top-aligned at ${width}px`);
  if (g.badge.left < g.copy.right - 0.5) throw new Error(`Open badge squeezes/overlaps title block at ${width}px`);
  if (g.card.left < 0 || g.card.right > g.viewport + 0.5) throw new Error(`Job card overflows viewport at ${width}px`);
  if (g.badge.right > g.card.right + 0.5) throw new Error(`Open badge escapes job card at ${width}px`);
  if (g.metrics.length !== 4) throw new Error(`Metric tiles changed at ${width}px`);
  const columnCount = g.metricColumns.trim().split(/\s+/).length;
  if (columnCount !== expectedMetricColumns) throw new Error(`Expected ${expectedMetricColumns} metric columns at ${width}px, got ${columnCount}: ${g.metricColumns}`);
}

for (const width of [360, 390, 412, 420]) {
  const { context, page } = await openPage(width);
  const g = await geometry(page);
  assertLayout(g, width, 2);
  console.log(`mobile-chrome ${width}px PASS`, { badge:g.badge, metricColumns:g.metricColumns });
  await context.close();
}

{
  const { context, page } = await openPage(1440, 900);
  const g = await geometry(page);
  assertLayout(g, 1440, 4);
  console.log('desktop 1440px PASS', { badge:g.badge, metricColumns:g.metricColumns });
  await context.close();
}

await browser.close();
console.log('Responsive job status badge verification passed');
