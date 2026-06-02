import React, { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';

function RainDrop({ delay, x, speed, height, width, sway }) {
  return (
    <motion.div
      style={{
        position: 'absolute',
        left: `${x}%`,
        top: -20,
        width: width,
        height: height,
        borderRadius: 9999,
        background: 'linear-gradient(180deg, rgba(23,162,219,0.0) 0%, rgba(23,162,219,0.45) 30%, rgba(23,162,219,0.75) 100%)',
        filter: width > 4 ? 'blur(0.5px)' : 'none',
      }}
      initial={{ y: -40, x: 0, opacity: 0 }}
      animate={{
        y: '110vh',
        x: [0, sway, -sway * 0.5, sway * 0.3, 0],
        opacity: [0, 0.3, 0.9, 0.9, 0],
      }}
      transition={{
        duration: speed,
        delay,
        ease: [0.25, 0.1, 0.25, 1],
        x: { duration: speed, delay, ease: 'easeInOut' },
      }}
    />
  );
}

function SplashRipple({ delay, x }) {
  return (
    <motion.div
      style={{
        position: 'absolute',
        left: `${x}%`,
        bottom: '8%',
        width: 0,
        height: 0,
        borderRadius: 9999,
        border: '2px solid rgba(23,162,219,0.4)',
      }}
      initial={{ width: 0, height: 0, opacity: 0.7 }}
      animate={{ width: 30, height: 10, opacity: 0 }}
      transition={{ duration: 0.8, delay: delay + 0.6, ease: 'easeOut' }}
    />
  );
}

export default function FigmaSplashScreen() {
  const navigate = useNavigate();
  const [transitioning, setTransitioning] = useState(false);

  const rainDrops = useMemo(() => {
    return Array.from({ length: 150 }).map((_, i) => ({
      id: i,
      x: (i * 0.7 + (i * 17.3) % 11) % 100,
      delay: (i * 0.02) % 1.2,
      speed: 1.2 + (i % 7) * 0.2,
      height: 25 + (i % 6) * 10,
      width: 2 + (i % 4),
      sway: 4 + (i % 5) * 3,
    }));
  }, []);

  const handleEnter = useCallback(() => {
    setTransitioning(true);
    setTimeout(() => navigate('/chat'), 1800);
  }, [navigate]);

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'black', overflow: 'hidden' }}>
      {/* Fullscreen background video */}
      <video
        autoPlay
        loop
        muted
        playsInline
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          zIndex: 1,
        }}
      >
        <source src="/static/video/background.mp4" type="video/mp4" />
      </video>

      {/* Rain transition overlay */}
      <AnimatePresence>
        {transitioning && (
          <>
            <motion.div
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 90,
                pointerEvents: 'none',
                overflow: 'hidden',
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.2 }}
            >
              {rainDrops.map((drop) => (
                <RainDrop
                  key={drop.id}
                  x={drop.x}
                  delay={drop.delay}
                  speed={drop.speed}
                  height={drop.height}
                  width={drop.width}
                  sway={drop.sway}
                />
              ))}
              {rainDrops.filter((_, i) => i % 3 === 0).map((drop) => (
                <SplashRipple key={`ripple-${drop.id}`} delay={drop.delay} x={drop.x} />
              ))}
            </motion.div>

            <motion.div
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 95,
                pointerEvents: 'none',
                background: 'linear-gradient(180deg, rgba(23,162,219,0.0) 0%, rgba(23,162,219,0.15) 50%, rgba(23,162,219,0.35) 100%)',
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.8, delay: 0.4 }}
            />

            <motion.div
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 96,
                pointerEvents: 'none',
                background: '#fff',
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.6, delay: 1.1 }}
            />
          </>
        )}
      </AnimatePresence>

      {/* CHAT WITH BLUE button */}
      <button
        onClick={handleEnter}
        disabled={transitioning}
        style={{
          position: 'fixed',
          bottom: 20,
          left: '50%',
          transform: 'translateX(-50%)',
          width: 268,
          height: 76,
          background: 'rgba(255, 255, 255, 0.8)',
          color: '#000000',
          fontWeight: 'bold',
          fontSize: 20,
          border: 'none',
          borderRadius: 40,
          cursor: transitioning ? 'default' : 'pointer',
          zIndex: 10,
          boxShadow: '0px 4px 12px rgba(0, 0, 0, 0.15)',
          transition: 'background 0.3s ease, color 0.3s ease',
          opacity: transitioning ? 0.7 : 1,
        }}
        onMouseEnter={e => { if (!transitioning) { e.target.style.background = '#0a92f3'; e.target.style.color = '#ffffff'; }}}
        onMouseLeave={e => { e.target.style.background = 'rgba(255, 255, 255, 0.8)'; e.target.style.color = '#000000'; }}
      >
        CHAT WITH BLUE
      </button>
    </div>
  );
}
