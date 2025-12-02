const { chromium } = require('playwright');
const http = require('http');

// Check if dev server is running
function checkServer(url) {
  return new Promise((resolve) => {
    const req = http.get(url, () => {
      resolve(true);
    });
    req.on('error', () => {
      resolve(false);
    });
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

(async () => {
  const port = 5173;
  const url = `http://localhost:${port}`;
  
  const serverRunning = await checkServer(url);
  if (!serverRunning) {
    console.log(`⚠️  Dev server not running on ${url}`);
    process.exit(1);
  }
  
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  console.log(`Navigating to ${url}...`);
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  
  // Get main-card bounding box
  const mainCard = await page.locator('.main-card');
  const mainCardBox = await mainCard.boundingBox();
  const mainCardStyles = await mainCard.evaluate((el) => {
    const computed = window.getComputedStyle(el);
    return {
      left: computed.left,
      right: computed.right,
      top: computed.top,
      bottom: computed.bottom,
      width: computed.width,
      margin: computed.margin,
    };
  });
  
  // Get download-transcript-container bounding box
  const container = await page.locator('.download-transcript-container');
  const containerBox = await container.boundingBox();
  const containerStyles = await container.evaluate((el) => {
    const computed = window.getComputedStyle(el);
    return {
      left: computed.left,
      right: computed.right,
      top: computed.top,
      bottom: computed.bottom,
      width: computed.width,
      margin: computed.margin,
    };
  });
  
  // Calculate gap
  let gap = null;
  if (mainCardBox && containerBox) {
    gap = containerBox.x - (mainCardBox.x + mainCardBox.width);
  }
  
  console.log('\n=== MAIN CARD & DOWNLOAD CONTAINER SPACING ===\n');
  
  console.log('Main Card:');
  if (mainCardBox) {
    console.log(`  X: ${mainCardBox.x.toFixed(2)}px, Y: ${mainCardBox.y.toFixed(2)}px`);
    console.log(`  Width: ${mainCardBox.width.toFixed(2)}px, Height: ${mainCardBox.height.toFixed(2)}px`);
    console.log(`  Right edge: ${(mainCardBox.x + mainCardBox.width).toFixed(2)}px`);
  }
  console.log('  Styles:');
  Object.entries(mainCardStyles).forEach(([key, value]) => {
    console.log(`    ${key}: ${value}`);
  });
  
  console.log('\nDownload Transcript Container:');
  if (containerBox) {
    console.log(`  X: ${containerBox.x.toFixed(2)}px, Y: ${containerBox.y.toFixed(2)}px`);
    console.log(`  Width: ${containerBox.width.toFixed(2)}px, Height: ${containerBox.height.toFixed(2)}px`);
    console.log(`  Left edge: ${containerBox.x.toFixed(2)}px`);
  }
  console.log('  Styles:');
  Object.entries(containerStyles).forEach(([key, value]) => {
    console.log(`    ${key}: ${value}`);
  });
  
  console.log('\n=== SPACING ANALYSIS ===');
  if (gap !== null) {
    console.log(`  Gap between main-card and container: ${gap.toFixed(2)}px`);
    const viewportWidth = await page.viewportSize().width;
    const gapPercent = (gap / viewportWidth * 100).toFixed(2);
    console.log(`  Gap as percentage: ${gapPercent}%`);
  } else {
    console.log('  ❌ Could not calculate spacing');
  }
  
  await browser.close();
})();

