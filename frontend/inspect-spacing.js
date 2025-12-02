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
  const port = 5173; // Vite default port
  const url = `http://localhost:${port}`;
  
  // Check if server is running
  const serverRunning = await checkServer(url);
  if (!serverRunning) {
    console.log(`⚠️  Dev server not running on ${url}`);
    console.log('Please start it with: npm run dev');
    console.log('Or we can inspect the built version...\n');
    process.exit(1);
  }
  
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  console.log(`Navigating to ${url}...`);
  await page.goto(url, { waitUntil: 'networkidle' });
  
  // Wait for the container to be visible
  const container = await page.locator('.download-transcript-container');
  await container.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {
    console.log('Container not found, waiting for page to load...');
  });
  
  await page.waitForTimeout(1000); // Wait a bit more for React to render
  
  // Get bounding box and computed styles
  const containerBox = await container.boundingBox();
  const containerStyles = await container.evaluate((el) => {
    const computed = window.getComputedStyle(el);
    return {
      gap: computed.gap,
      padding: computed.padding,
      margin: computed.margin,
      display: computed.display,
      flexDirection: computed.flexDirection,
      justifyContent: computed.justifyContent,
      alignItems: computed.alignItems,
      position: computed.position,
      top: computed.top,
      right: computed.right,
      left: computed.left,
      bottom: computed.bottom,
      width: computed.width,
      height: computed.height,
    };
  });
  
  // Get child elements
  const ellipse = await page.locator('.download-transcript-ellipse');
  const iconContainer = await page.locator('.download-transcript-icon-container');
  
  const ellipseExists = await ellipse.count() > 0;
  const iconContainerExists = await iconContainer.count() > 0;
  
  let ellipseBox = null;
  let iconContainerBox = null;
  let ellipseStyles = {};
  let iconContainerStyles = {};
  
  if (ellipseExists) {
    ellipseBox = await ellipse.boundingBox();
    ellipseStyles = await ellipse.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return {
        width: computed.width,
        height: computed.height,
        margin: computed.margin,
        padding: computed.padding,
      };
    });
  }
  
  if (iconContainerExists) {
    iconContainerBox = await iconContainer.boundingBox();
    iconContainerStyles = await iconContainer.evaluate((el) => {
      const computed = window.getComputedStyle(el);
      return {
        width: computed.width,
        height: computed.height,
        margin: computed.margin,
        padding: computed.padding,
      };
    });
  }
  
  // Calculate spacing
  let spacing = null;
  if (ellipseBox && iconContainerBox) {
    spacing = iconContainerBox.x - (ellipseBox.x + ellipseBox.width);
  }
  
  console.log('\n=== DOWNLOAD TRANSCRIPT CONTAINER SPACING INSPECTION ===\n');
  console.log('Container Position & Size:');
  if (containerBox) {
    console.log(`  X: ${containerBox.x.toFixed(2)}px, Y: ${containerBox.y.toFixed(2)}px`);
    console.log(`  Width: ${containerBox.width.toFixed(2)}px, Height: ${containerBox.height.toFixed(2)}px`);
  } else {
    console.log('  Container not found or not visible');
  }
  
  console.log('\nContainer Styles:');
  Object.entries(containerStyles).forEach(([key, value]) => {
    console.log(`  ${key}: ${value}`);
  });
  
  if (ellipseExists) {
    console.log('\n🏠 Home Icon (Ellipse):');
    if (ellipseBox) {
      console.log(`  Position: X=${ellipseBox.x.toFixed(2)}px, Y=${ellipseBox.y.toFixed(2)}px`);
      console.log(`  Size: ${ellipseBox.width.toFixed(2)}px × ${ellipseBox.height.toFixed(2)}px`);
    }
    console.log('  Styles:');
    Object.entries(ellipseStyles).forEach(([key, value]) => {
      console.log(`    ${key}: ${value}`);
    });
  } else {
    console.log('\n⚠️  Home Icon (Ellipse) not found!');
  }
  
  if (iconContainerExists) {
    console.log('\n📥 Download Icon Container:');
    if (iconContainerBox) {
      console.log(`  Position: X=${iconContainerBox.x.toFixed(2)}px, Y=${iconContainerBox.y.toFixed(2)}px`);
      console.log(`  Size: ${iconContainerBox.width.toFixed(2)}px × ${iconContainerBox.height.toFixed(2)}px`);
    }
    console.log('  Styles:');
    Object.entries(iconContainerStyles).forEach(([key, value]) => {
      console.log(`    ${key}: ${value}`);
    });
  } else {
    console.log('\n⚠️  Download Icon Container not found!');
  }
  
  console.log('\n=== SPACING ANALYSIS ===');
  if (spacing !== null) {
    const expectedGap = 15; // From CSS
    const gapFromStyles = parseInt(containerStyles.gap) || 0;
    console.log(`  Measured gap between icons: ${spacing.toFixed(2)}px`);
    console.log(`  CSS gap property: ${containerStyles.gap}`);
    console.log(`  Expected gap (from CSS): ${expectedGap}px`);
    console.log(`  Difference: ${(spacing - expectedGap).toFixed(2)}px`);
    
    if (Math.abs(spacing - expectedGap) > 1) {
      console.log(`  ⚠️  WARNING: Gap doesn't match expected value!`);
    }
  } else {
    console.log('  ❌ Could not calculate spacing (elements not found or not visible)');
  }
  
  // Take a screenshot
  const screenshotPath = 'container-inspection.png';
  await page.screenshot({ path: screenshotPath, fullPage: false });
  console.log(`\n📸 Screenshot saved as: ${screenshotPath}`);
  
  console.log('\nBrowser will stay open for 5 seconds for manual inspection...');
  await page.waitForTimeout(5000);
  
  await browser.close();
})();
