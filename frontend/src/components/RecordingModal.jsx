import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import svgPaths from "../imports/svg-s7e7bo9si0";
import { Square } from "lucide-react";
import "./RecordingModal.css";

function BlueCharacter({
  isListening,
  isSpeaking,
}) {
  return (
    <motion.div
      className="absolute inset-[29.49%_35.47%_28.92%_35.16%]"
      data-name="Blue Character"
      animate={{
        y: isSpeaking
          ? [0, -8, 0]
          : isListening
            ? [0, -3, 0]
            : 0,
        scale: isSpeaking ? [1, 1.02, 1] : 1,
      }}
      transition={{
        duration: isSpeaking ? 1.5 : 3,
        repeat: isListening || isSpeaking ? Infinity : 0,
        ease: "easeInOut",
      }}
    >
      <div className="absolute inset-[-0.23%_-1.18%_-2.11%_-0.94%]">
        <svg
          className="block size-full"
          fill="none"
          preserveAspectRatio="xMidYMid meet"
          viewBox="0 0 432 436"
        >
          <g filter="url(#filter0_d_1_66)" id="Blue Character">
            <g id="Group">
              <path
                d={svgPaths.p1fba0f80}
                fill="var(--fill-0, #55B7D5)"
                id="Vector"
                stroke="var(--stroke-0, #407498)"
                strokeMiterlimit="10"
                strokeWidth="2"
              />
              <path
                d={svgPaths.pb8a20c0}
                fill="var(--fill-0, #55B7D5)"
                id="Vector_2"
                stroke="var(--stroke-0, #407498)"
                strokeMiterlimit="10"
                strokeWidth="2"
              />
            </g>
            <path
              d={svgPaths.p202dd100}
              fill="var(--fill-0, #55B7D5)"
              id="Vector_3"
              stroke="var(--stroke-0, #407498)"
              strokeMiterlimit="10"
              strokeWidth="2"
            />
            <path
              d={svgPaths.p3226d80}
              fill="var(--fill-0, #55B7D5)"
              id="Vector_4"
              stroke="var(--stroke-0, #407498)"
              strokeMiterlimit="10"
              strokeWidth="2"
            />
            <path
              d={svgPaths.p10b79d80}
              fill="var(--fill-0, #55B7D5)"
              id="Vector_5"
              stroke="var(--stroke-0, #407498)"
              strokeMiterlimit="10"
              strokeWidth="2"
            />
            <path
              d={svgPaths.p16c27f00}
              fill="var(--fill-0, #55B7D5)"
              id="Vector_6"
              stroke="var(--stroke-0, #407498)"
              strokeMiterlimit="10"
              strokeWidth="2"
            />
            <g id="Group_2">
              {/* Eyes - blink when speaking or listening */}
              <motion.path
                d={svgPaths.pefd9092}
                id="Vector_7"
                stroke="var(--stroke-0, #223643)"
                strokeMiterlimit="10"
                strokeWidth="3"
                animate={{
                  scaleY: isSpeaking || isListening
                    ? [1, 0.1, 1, 1, 1, 1, 0.1, 1]
                    : 1,
                }}
                transition={{
                  duration: 2,
                  repeat: (isSpeaking || isListening) ? Infinity : 0,
                  ease: "easeInOut",
                }}
                style={{ transformOrigin: "center" }}
              />
              <motion.path
                d={svgPaths.p32038b00}
                id="Vector_8"
                stroke="var(--stroke-0, #223643)"
                strokeMiterlimit="10"
                strokeWidth="3"
                animate={{
                  scaleY: isSpeaking || isListening
                    ? [1, 0.1, 1, 1, 1, 1, 0.1, 1]
                    : 1,
                }}
                transition={{
                  duration: 2,
                  repeat: (isSpeaking || isListening) ? Infinity : 0,
                  ease: "easeInOut",
                }}
                style={{ transformOrigin: "center" }}
              />
              <path
                d={svgPaths.p3ee1fa80}
                fill="var(--fill-0, #223643)"
                id="Vector_9"
              />
              {/* Mouth - animated for speaking or listening with more dynamic movement */}
              <motion.path
                d={svgPaths.p19ba8a80}
                fill="var(--fill-0, #E47E77)"
                id="Vector_10"
                animate={{
                  scaleY: isSpeaking || isListening
                    ? [1, 1.4, 1.1, 1.5, 1, 1.3, 1.15, 1.2, 1]
                    : 1,
                  scaleX: isSpeaking || isListening
                    ? [
                        1, 0.95, 1.02, 0.93, 1, 0.96, 1.01,
                        0.97, 1,
                      ]
                    : 1,
                }}
                transition={{
                  duration: 1.2,
                  repeat: (isSpeaking || isListening) ? Infinity : 0,
                  ease: "easeInOut",
                }}
                style={{ transformOrigin: "center" }}
              />
              {/* Eyebrows - animated when speaking or listening */}
              <motion.path
                d={svgPaths.p1b235200}
                fill="var(--fill-0, #223643)"
                id="Vector_11"
                animate={{
                  y: isSpeaking || isListening
                    ? [0, -2, 0, -1, 0]
                    : 0,
                }}
                transition={{
                  duration: 1.5,
                  repeat: (isSpeaking || isListening) ? Infinity : 0,
                  ease: "easeInOut",
                }}
                style={{ transformOrigin: "center" }}
              />
              <motion.path
                d={svgPaths.p1228fd80}
                fill="var(--fill-0, #223643)"
                id="Vector_12"
                animate={{
                  y: isSpeaking || isListening
                    ? [0, -2, 0, -1, 0]
                    : 0,
                }}
                transition={{
                  duration: 1.5,
                  repeat: (isSpeaking || isListening) ? Infinity : 0,
                  ease: "easeInOut",
                }}
                style={{ transformOrigin: "center" }}
              />
            </g>
          </g>
          <defs>
            <filter
              colorInterpolationFilters="sRGB"
              filterUnits="userSpaceOnUse"
              height="435.87"
              id="filter0_d_1_66"
              width="431.996"
              x="-1.49012e-08"
              y="0"
            >
              <feFlood
                floodOpacity="0"
                result="BackgroundImageFix"
              />
              <feColorMatrix
                in="SourceAlpha"
                result="hardAlpha"
                type="matrix"
                values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"
              />
              <feOffset dy="4" />
              <feGaussianBlur stdDeviation="2" />
              <feComposite in2="hardAlpha" operator="out" />
              <feColorMatrix
                type="matrix"
                values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.25 0"
              />
              <feBlend
                in2="BackgroundImageFix"
                mode="normal"
                result="effect1_dropShadow_1_66"
              />
              <feBlend
                in="SourceGraphic"
                in2="effect1_dropShadow_1_66"
                mode="normal"
                result="shape"
              />
            </filter>
          </defs>
        </svg>
      </div>
    </motion.div>
  );
}

// Listening ripple animations
function ListeningRipples() {
  return (
    <div className="absolute inset-[29.49%_35.47%_28.92%_35.16%] pointer-events-none">
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className="absolute inset-0"
          initial={{ scale: 1, opacity: 0 }}
          animate={{
            scale: [1, 1.8, 2.2],
            opacity: [0.6, 0.3, 0],
          }}
          transition={{
            duration: 3,
            repeat: Infinity,
            delay: i * 1,
            ease: "easeOut",
          }}
        >
          <div
            className="absolute inset-0 border-4 border-[#55B7D5] rounded-full"
            style={{ filter: "blur(2px)" }}
          />
        </motion.div>
      ))}
    </div>
  );
}

// Speaking waveforms animations
function SpeakingWaveforms() {
  return (
    <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none">
      {/* Circular glowing rings around character */}
      <motion.div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px]"
        animate={{
          scale: [1, 1.1, 1],
          opacity: [0.6, 0.9, 0.6],
        }}
        transition={{
          duration: 1.5,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      >
        <div
          className="absolute inset-0 border-[3px] border-[#55B7D5] rounded-full"
          style={{
            filter: "blur(3px)",
            boxShadow: "0 0 20px rgba(85, 183, 213, 0.6)",
          }}
        />
      </motion.div>

      <motion.div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[550px]"
        animate={{
          scale: [1, 1.15, 1],
          opacity: [0.4, 0.7, 0.4],
        }}
        transition={{
          duration: 1.8,
          repeat: Infinity,
          ease: "easeInOut",
          delay: 0.3,
        }}
      >
        <div
          className="absolute inset-0 border-[2px] border-[#337CC1] rounded-full"
          style={{
            filter: "blur(4px)",
            boxShadow: "0 0 30px rgba(51, 124, 193, 0.5)",
          }}
        />
      </motion.div>
    </div>
  );
}

export default function RecordingModal({ isVisible, onClose, transcript = "" }) {
  const [state, setState] = useState("listening");
  const [mounted, setMounted] = useState(false);
  const [displayedText, setDisplayedText] = useState("");

  // Ensure component is mounted before rendering portal
  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  // Start listening when modal opens
  useEffect(() => {
    if (isVisible) {
      setState("listening");
      setDisplayedText(""); // Reset text when modal opens
    } else {
      setState("idle");
    }
  }, [isVisible]);

  // Animate text appearance as it's transcribed
  useEffect(() => {
    if (!transcript) {
      setDisplayedText("");
      return;
    }

    if (transcript.length > displayedText.length) {
      // New text added - show it immediately for real-time feel
      // But animate the new characters appearing
      const newChars = transcript.slice(displayedText.length);
      
      // For better UX, show text immediately but animate the last few characters
      if (newChars.length > 10) {
        // If a lot of new text, show most immediately, animate last part
        const immediateText = transcript.slice(0, transcript.length - 5);
        setDisplayedText(immediateText);
        
        // Animate the last few characters
        let index = immediateText.length;
        const interval = setInterval(() => {
          if (index < transcript.length) {
            setDisplayedText(transcript.slice(0, index + 1));
            index++;
          } else {
            clearInterval(interval);
          }
        }, 50);
        
        return () => clearInterval(interval);
      } else {
        // Small amount of new text - animate it
        let index = displayedText.length;
        const interval = setInterval(() => {
          if (index < transcript.length) {
            setDisplayedText(transcript.slice(0, index + 1));
            index++;
          } else {
            clearInterval(interval);
          }
        }, 30);
        
        return () => clearInterval(interval);
      }
    } else if (transcript !== displayedText) {
      // Direct update if transcript changed (shouldn't happen often)
      setDisplayedText(transcript);
    }
  }, [transcript, displayedText]);

  if (!mounted) return null;

  const modalContent = (
    <AnimatePresence>
      {isVisible && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="recording-modal-backdrop"
            style={{
              backgroundColor: 'rgba(0, 0, 0, 0.6)',
              backdropFilter: 'blur(4px)',
            }}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="recording-modal-container"
            style={{
              borderRadius: '24px',
              boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
              overflow: 'hidden',
              background: 'transparent',
              backdropFilter: 'blur(20px)'
            }}
          >
            {/* Content */}
            <div 
              className="relative size-full" 
              data-name="Desktop - 6"
              style={{
                background: 'rgba(125, 200, 224, 0.7)',
                borderRadius: '24px',
                backdropFilter: 'blur(30px)',
                border: '1px solid rgba(255, 255, 255, 0.3)',
                boxShadow: 'inset 0 1px 0 0 rgba(255, 255, 255, 0.2)',
                overflow: 'hidden'
              }}
            >
              <div 
                style={{
                  position: 'absolute',
                  top: '20px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  width: '60%',
                  display: 'flex',
                  flexDirection: 'column',
                  fontFamily: "'Libre Franklin', -apple-system, BlinkMacSystemFont, sans-serif",
                  fontWeight: 800,
                  lineHeight: 'normal',
                  color: '#7dc8e0',
                  fontSize: 'clamp(28px, 4vw, 48px)',
                  letterSpacing: '0.64px',
                  justifyContent: 'center',
                  alignItems: 'center',
                  textAlign: 'center',
                  overflow: 'hidden',
                  zIndex: 5
                }}
              >
                <p style={{ lineHeight: '1.2', margin: 0, padding: 0, whiteSpace: 'nowrap' }}>Chat With Blue</p>
              </div>

              {/* Listening ripples */}
              <AnimatePresence>
                {state === "listening" && <ListeningRipples />}
              </AnimatePresence>

              {/* Blue Character */}
              <BlueCharacter
                isListening={state === "listening"}
                isSpeaking={state === "speaking"}
              />

              {/* Speaking waveforms */}
              <AnimatePresence>
                {state === "speaking" && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="absolute inset-0"
                  >
                    <SpeakingWaveforms />
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Transcription Preview */}
              <motion.div
                initial={{ opacity: 0, y: 20, x: '-50%' }}
                animate={{ opacity: 1, y: 0, x: '-50%' }}
                style={{
                  position: 'absolute',
                  bottom: '140px',
                  left: '50%',
                  width: '85%',
                  maxWidth: '800px',
                  zIndex: 20,
                  padding: '0 20px',
                  boxSizing: 'border-box'
                }}
              >
                <div
                  style={{
                    background: displayedText ? 'rgba(255, 255, 255, 0.3)' : 'rgba(255, 255, 255, 0.2)',
                    borderRadius: '20px',
                    padding: '24px 32px',
                    boxShadow: '0 10px 40px rgba(0, 0, 0, 0.15)',
                    backdropFilter: 'blur(10px)',
                    border: 'none',
                    minHeight: '80px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '100%',
                    boxSizing: 'border-box',
                    maxWidth: '100%'
                  }}
                >
                  {displayedText ? (
                    <motion.p
                      key={displayedText}
                      initial={{ opacity: 0, scale: 0.98 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.2 }}
                      style={{
                        fontFamily: "'SF Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                        fontSize: '20px',
                        lineHeight: '1.6',
                        color: '#254c63',
                        margin: 0,
                        wordWrap: 'break-word',
                        whiteSpace: 'pre-wrap',
                        width: '100%',
                        textShadow: '0 1px 2px rgba(255, 255, 255, 0.8)'
                      }}
                    >
                      {displayedText}
                      {transcript && transcript.length > displayedText.length && (
                        <motion.span
                          animate={{ opacity: [1, 0.3, 1] }}
                          transition={{
                            duration: 1,
                            repeat: Infinity,
                            ease: "easeInOut"
                          }}
                          style={{
                            color: '#8C1D40',
                            fontWeight: 'bold',
                            marginLeft: '2px'
                          }}
                        >
                          |
                        </motion.span>
                      )}
                    </motion.p>
                  ) : (
                    <motion.p
                      animate={{ opacity: [0.5, 1, 0.5] }}
                      transition={{
                        duration: 2,
                        repeat: Infinity,
                        ease: "easeInOut"
                      }}
                      style={{
                        fontFamily: "'SF Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                        fontSize: '18px',
                        color: '#8C1D40',
                        margin: 0,
                        fontStyle: 'italic',
                        textShadow: '0 1px 2px rgba(255, 255, 255, 0.8)'
                      }}
                    >
                      Listening...
                    </motion.p>
                  )}
                </div>
              </motion.div>

              {/* Interactive button */}
              <div
                style={{
                  position: 'absolute',
                  bottom: '40px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  zIndex: 30
                }}
              >
                <button
                  onClick={onClose}
                  style={{
                    position: 'relative',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: 0
                  }}
                >
                  <div
                    style={{
                      backgroundColor: '#8C1D40',
                      position: 'relative',
                      borderRadius: '50%',
                      width: '80px',
                      height: '80px',
                      transition: 'all 0.2s ease',
                      cursor: 'pointer'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = '#7a1937';
                      e.currentTarget.style.transform = 'scale(1.05)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = '#8C1D40';
                      e.currentTarget.style.transform = 'scale(1)';
                    }}
                    data-name="Interact with Blue"
                  >
                    <div
                      aria-hidden="true"
                      style={{
                        position: 'absolute',
                        border: '2px solid #5a1229',
                        inset: '-2px',
                        pointerEvents: 'none',
                        borderRadius: '50%'
                      }}
                    />
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'row',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: '100%',
                        height: '100%'
                      }}
                    >
                      <Square
                        style={{
                          width: '40px',
                          height: '40px',
                          color: 'white',
                          fill: 'white'
                        }}
                      />
                    </div>
                  </div>
                </button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );

  return createPortal(modalContent, document.body);
}
