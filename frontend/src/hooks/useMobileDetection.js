import { useState, useEffect } from 'react';

/**
 * Custom hook to detect mobile devices
 * Returns true if the device is a mobile device or if the viewport is mobile-sized
 */
export function useMobileDetection() {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      // Check viewport width (primary method)
      const isMobileWidth = window.innerWidth <= 768;
      
      // Check user agent for mobile devices
      const userAgent = navigator.userAgent || navigator.vendor || window.opera;
      const isMobileUA = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i.test(userAgent.toLowerCase());
      
      // Check for touch capability
      const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
      
      // Consider mobile if any of these conditions are true
      setIsMobile(isMobileWidth || (isMobileUA && isTouchDevice));
    };

    // Check on mount
    checkMobile();

    // Check on resize
    window.addEventListener('resize', checkMobile);
    
    // Check on orientation change
    window.addEventListener('orientationchange', checkMobile);

    return () => {
      window.removeEventListener('resize', checkMobile);
      window.removeEventListener('orientationchange', checkMobile);
    };
  }, []);

  return isMobile;
}

/**
 * Hook to get detailed device information
 */
export function useDeviceInfo() {
  const [deviceInfo, setDeviceInfo] = useState({
    isMobile: false,
    isTablet: false,
    isDesktop: true,
    isTouchDevice: false,
    userAgent: '',
    viewportWidth: 0,
  });

  useEffect(() => {
    const updateDeviceInfo = () => {
      const width = window.innerWidth;
      const userAgent = navigator.userAgent || navigator.vendor || window.opera;
      const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
      
      const isMobileWidth = width <= 768;
      const isTabletWidth = width > 768 && width <= 1024;
      
      const isMobileUA = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i.test(userAgent.toLowerCase());
      const isTabletUA = /ipad|android(?!.*mobile)/i.test(userAgent.toLowerCase());

      setDeviceInfo({
        isMobile: isMobileWidth || (isMobileUA && !isTabletUA),
        isTablet: isTabletWidth || isTabletUA,
        isDesktop: width > 1024 && !isMobileUA,
        isTouchDevice: isTouchDevice,
        userAgent: userAgent,
        viewportWidth: width,
      });
    };

    updateDeviceInfo();
    window.addEventListener('resize', updateDeviceInfo);
    window.addEventListener('orientationchange', updateDeviceInfo);

    return () => {
      window.removeEventListener('resize', updateDeviceInfo);
      window.removeEventListener('orientationchange', updateDeviceInfo);
    };
  }, []);

  return deviceInfo;
}

