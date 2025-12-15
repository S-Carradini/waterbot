import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useMobileDetection } from '../hooks/useMobileDetection';
import './MobileOnlyGuard.css';

/**
 * Component that only renders children on mobile devices
 * Shows a message and redirects desktop users
 */
export default function MobileOnlyGuard({ children }) {
  const isMobile = useMobileDetection();
  const navigate = useNavigate();

  React.useEffect(() => {
    if (!isMobile && window.innerWidth > 768) {
      // Redirect desktop users to desktop version after a short delay
      const timer = setTimeout(() => {
        navigate('/waterbot', { replace: true });
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [isMobile, navigate]);

  if (!isMobile) {
    return (
      <div className="mobile-only-message">
        <div className="mobile-only-content">
          <h2>Mobile Version</h2>
          <p>This version is optimized for mobile devices.</p>
          <p>Redirecting you to the desktop version...</p>
          <button 
            className="mobile-only-button"
            onClick={() => navigate('/waterbot')}
          >
            Go to Desktop Version Now
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

