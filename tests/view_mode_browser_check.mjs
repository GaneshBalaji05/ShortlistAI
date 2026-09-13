import { chromium } from 'playwright';

const root = process.env.SHORTLISTAI_URL || 'https://shortlistai-view-mode-preview.onrender.com';
const browser = await chromium.launch({ headless: true });

async function verifyMobileViewport() {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto(`${root}/app`, { waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForSelector('#frViewModeControl', { state: 'visible', timeout: 60000 });

  const mobile = page.locator('#frViewModeControl [data-view="mobile"]');
  const desktop = page.locator('#frViewModeControl [data-view="desktop"]');
  if (!(await mobile.isVisible()) || !(await desktop.isVisible())) throw new Error('Both view buttons are not visible on mobile');

  await desktop.click();
  await page.waitForFunction(() => document.body.classList.contains('force-desktop'));
  const desktopStored = await page.evaluate(() => localStorage.getItem('shortlistai-view-mode'));
  if (desktopStored !== 'desktop') throw new Error(`Desktop choice not persisted: ${desktopStored}`);

  await page.reload({ waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForSelector('#frViewModeControl', { state: 'visible', timeout: 60000 });
  await page.waitForFunction(() => document.body.classList.contains('force-desktop'));
  const desktopActive = await page.locator('#frViewModeControl [data-view="desktop"]').getAttribute('aria-pressed');
  if (desktopActive !== 'true') throw new Error('Desktop View did not remain active after reload');

  await page.locator('#frViewModeControl [data-view="mobile"]').click();
  await page.waitForFunction(() => document.body.classList.contains('force-mobile') && !document.body.classList.contains('force-desktop'));
  const mobileStored = await page.evaluate(() => localStorage.getItem('shortlistai-view-mode'));
  if (mobileStored !== 'mobile') throw new Error(`Mobile choice not persisted: ${mobileStored}`);

  await context.close();
}

async function verifyDesktopViewport() {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${root}/app`, { waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForSelector('#frViewModeControl', { state: 'visible', timeout: 60000 });
  if (!(await page.locator('#frViewModeControl [data-view="mobile"]').isVisible())) throw new Error('Mobile View control is hidden on desktop');
  if (!(await page.locator('#frViewModeControl [data-view="desktop"]').isVisible())) throw new Error('Desktop View control is hidden on desktop');

  await page.locator('#frViewModeControl [data-view="mobile"]').click();
  await page.waitForFunction(() => document.body.classList.contains('force-mobile'));
  const width = await page.evaluate(() => document.body.getBoundingClientRect().width);
  if (width > 500) throw new Error(`Forced mobile layout did not narrow: ${width}`);

  await page.locator('#frViewModeControl [data-view="desktop"]').click();
  await page.waitForFunction(() => !document.body.classList.contains('force-mobile'));
  const mode = await page.evaluate(() => document.documentElement.dataset.shortlistView);
  if (mode !== 'desktop') throw new Error(`Desktop mode marker incorrect: ${mode}`);

  await context.close();
}

try {
  await verifyMobileViewport();
  await verifyDesktopViewport();
  console.log('Interactive Mobile View/Desktop View browser verification passed');
} finally {
  await browser.close();
}
