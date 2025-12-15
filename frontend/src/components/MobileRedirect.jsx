import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMobileDetection } from '../hooks/useMobileDetection';

/**
 * Component that redirects mobile users to mobile version
 * and desktop users to desktop version
 */
export default function MobileRedirect({ children, mobilePath = '/mobile', desktopPath = '/waterbot' }) {
  const isMobile = useMobileDetection();
  const navigate = useNavigate();

  useEffect(() => {
    // Only redirect if we're on the wrong version
    const currentPath = window.location.pathname;
    
    if (isMobile && !currentPath.includes('/mobile') && currentPath === '/waterbot') {
      navigate(mobilePath, { replace: true });
    } else if (!isMobile && currentPath === '/mobile') {
      navigate(desktopPath, { replace: true });
    }
  }, [isMobile, navigate, mobilePath, desktopPath]);

  return <>{children}</>;
}

