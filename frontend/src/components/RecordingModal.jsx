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

  // Ensure component is mounted before rendering portal
  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  // Start listening when modal opens
  useEffect(() => {
    if (isVisible) {
      setState("listening");
    } else {
      setState("idle");
    }
  }, [isVisible]);

  if (!mounted) return null;

  const modalContent = (
    <AnimatePresence>
      {isVisible && (
        <>
          {/* Fuzzy backdrop with blur effect - full screen */}
          <motion.div
            initial={{ opacity: 0, backdropFilter: 'blur(0px)' }}
            animate={{ opacity: 1, backdropFilter: 'blur(8px)' }}
            exit={{ opacity: 0, backdropFilter: 'blur(0px)' }}
            transition={{ duration: 0.3 }}
            className="recording-modal-backdrop"
            style={{
              backgroundColor: 'rgba(0, 0, 0, 0.2)',
              backdropFilter: 'blur(8px)',
              pointerEvents: 'none',
            }}
          />
          
          {/* Clear overlay for input area and language toggle - covers entire input-wrapper area */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            style={{
              position: 'fixed',
              top: '87.21%',
              right: '1.81%',
              bottom: '5.57%',
              left: '1.74%',
              backgroundColor: '#7dc8e0', /* Match page background */
              borderRadius: '16px', /* Match input container border radius */
              pointerEvents: 'none',
              zIndex: 1000, /* Between backdrop (999) and input (1001) */
            }}
          />

          {/* Modal container - transparent, only for positioning */}
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="recording-modal-container"
            style={{
              background: 'transparent',
              pointerEvents: 'none',
            }}
          >
            {/* Content - transparent, only blue character visible */}
            <div 
              className="relative size-full" 
              data-name="Desktop - 6"
              style={{
                background: 'transparent',
                pointerEvents: 'none',
              }}
            >
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
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );

  return createPortal(modalContent, document.body);
}
