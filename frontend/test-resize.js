const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  
  const checkPosition = async (viewportWidth) => {
    await page.setViewportSize({ width: viewportWidth, height: 800 });
    await page.waitForTimeout(500);
    
    const container = await page.locator('.download-transcript-container');
    const mainCard = await page.locator('.main-card');
    
    const containerBox = await container.boundingBox();
    const mainCardBox = await mainCard.boundingBox();
    
    const containerStyles = await container.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return {
        left: computed.left,
        right: computed.right,
      };
    });
    
    const gap = containerBox.x - (mainCardBox.x + mainCardBox.width);
    
    return {
      viewportWidth,
      containerX: containerBox.x,
      mainCardRight: mainCardBox.x + mainCardBox.width,
      gap,
      left: containerStyles.left,
      right: containerStyles.right,
    };
  };
  
  console.log('\n=== RESIZE TEST ===\n');
  
  const widths = [1280, 1600, 1920, 2560];
  const results = [];
  
  for (const width of widths) {
    const result = await checkPosition(width);
    results.push(result);
    console.log(`Viewport: ${width}px`);
    console.log(`  Container X: ${result.containerX.toFixed(2)}px`);
    console.log(`  Main Card Right: ${result.mainCardRight.toFixed(2)}px`);
    console.log(`  Gap: ${result.gap.toFixed(2)}px`);
    console.log(`  CSS left: ${result.left}, right: ${result.right}`);
    console.log('');
  }
  
  // Check gap consistency
  const gaps = results.map(r => r.gap);
  const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  const gapVariance = Math.max(...gaps) - Math.min(...gaps);
  
  console.log('=== CONSISTENCY ANALYSIS ===');
  console.log(`Average gap: ${avgGap.toFixed(2)}px`);
  console.log(`Gap variance: ${gapVariance.toFixed(2)}px`);
  
  if (gapVariance > 10) {
    console.log('❌ Gap is NOT consistent across viewport sizes');
    console.log('   Recommendation: Use fixed pixel spacing or calc()');
  } else {
    console.log('✅ Gap is consistent across viewport sizes');
  }
  
  await browser.close();
})();

