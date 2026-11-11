import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { sendRiverbotMessage } from "../../services/api"
import "../../styles/riverbot.css"
import {
  ArrowUp,
  ArrowRight,
  AudioLines,
  Check,
  Copy,
  Download,
  FileText,
  Info,
  Home,
  Leaf,
  Mic,
  MicOff,
  Plus,
  Pause,
  Play,
  Sparkles,
  Waves,
  X,
} from "lucide-react"

type Message = {
  role: "user" | "river"
  text: string
}
type Recognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  onresult: ((event: {
    results: { [index: number]: { [index: number]: { transcript: string } } }
  }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}
const prompts = [
  "What's your story?",
  "Who depends on you?",
  "How have humans changed you?",
  "What does your future hold?",
]
const mascot = "/riverbot-assets/a90eb.svg"
const riverPoster = "/riverbot-assets/river.jpg"

const RIVER_ERROR =
  "I lost the current for a moment. Please try asking again."

// The backend returns HTML-ish text (</p><p> and <br>); render it as plain text.
function replyToText(html: string) {
  const withBreaks = html
    .replace(/<\/p>\s*<p>/gi, "\n\n")
    .replace(/<br\s*\/?>/gi, "\n")
  const doc = new DOMParser().parseFromString(withBreaks, "text/html")
  return (doc.body.textContent || "").trim()
}

function Mascot({
  size = "large",
  thinking = false,
}: {
  size?: "small" | "large" | "voice"
  thinking?: boolean
}) {
  return (
    <div
      className={`relative shrink-0 ${
        size === "small"
          ? "w-11"
          : size === "voice"
            ? "w-[clamp(9rem,26dvh,16rem)]"
            : "w-32 sm:w-40"
      }`}
    >
      <img
        src={mascot}
        alt="Riverbot, a smiling turquoise water character"
        className={`relative z-10 block h-auto w-full ${
          size !== "small"
            ? "motion-safe:animate-[float_6s_ease-in-out_infinite]"
            : ""
        } ${thinking ? "opacity-80" : ""}`}
      />
      {size !== "small" && (
        <div className="absolute -bottom-1 left-1/2 h-5 w-[125%] -translate-x-1/2 rounded-[50%] border border-[#c9ece5]/35 bg-[#b4e7d7]/10 shadow-[0_0_35px_#abe6d320]" />
      )}
    </div>
  )
}

function IconButton({
  children,
  label,
  onClick,
  className = "",
}: {
  children: ReactNode
  label: string
  onClick: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`flex size-11 items-center justify-center rounded-full text-white/80 transition hover:-translate-y-0.5 hover:bg-white/10 hover:text-white ${className}`}
    >
      {children}
    </button>
  )
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    ref.current?.showModal()
  }, [])
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className="fixed inset-0 m-auto max-h-[90dvh] w-[calc(100%-32px)] max-w-md overflow-y-auto rounded-[30px] border border-[#cadbd0] bg-[#f4f5ed] p-7 text-[#234b41] shadow-2xl backdrop:bg-[#071e19]/60 backdrop:backdrop-blur-md"
    >
      <div className="mb-5 flex items-center justify-between gap-3">
        <h2 id={titleId} className="font-display text-2xl font-bold">
          {title}
        </h2>
        <IconButton
          label="Close dialog"
          onClick={onClose}
          className="!text-[#234b41] hover:!bg-black/5"
        >
          <X size={20} />
        </IconButton>
      </div>
      {children}
    </dialog>
  )
}

function makePdf(text: string) {
  const lines = text
    .normalize("NFKD")
    .replace(/[^\x20-\x7E\n]/g, "")
    .split("\n")
    .flatMap((line) => line.match(/.{1,85}(?:\s|$)|.{1,85}/g) || [""])
  const pages = Array.from(
    { length: Math.max(1, Math.ceil(lines.length / 46)) },
    (_, index) => lines.slice(index * 46, index * 46 + 46),
  )
  const objects: string[] = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    `<< /Type /Pages /Kids [${pages.map((_, index) => `${4 + index * 2} 0 R`).join(" ")} ] /Count ${pages.length} >>`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ]
  pages.forEach((page, index) => {
    objects.push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + index * 2} 0 R >>`,
    )
    const stream = `BT /F1 11 Tf 45 745 Td 15 TL ${page.map((line) => `(${line.replace(/([\\()])/g, "\\$1")}) Tj T*`).join("\n")} ET`
    objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`)
  })
  let pdf = "%PDF-1.4\n"
  const offsets = [0]
  objects.forEach((object, index) => {
    offsets.push(pdf.length)
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const start = pdf.length
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join(
      "",
    )}trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`
  return pdf
}

function SplashScreen({
  onStart,
  hasConversation,
}: {
  onStart: (background: string) => void
  hasConversation: boolean
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [videoError, setVideoError] = useState(false)

  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)")
    function syncPlayback() {
      if (preference.matches) videoRef.current?.pause()
      else videoRef.current?.play().catch(() => setPlaying(false))
    }
    syncPlayback()
    preference.addEventListener("change", syncPlayback)
    return () => preference.removeEventListener("change", syncPlayback)
  }, [])

  function startChat() {
    const video = videoRef.current
    if (
      !video ||
      videoError ||
      video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
      !video.videoWidth
    ) {
      onStart(riverPoster)
      return
    }

    video.pause()
    const canvas = document.createElement("canvas")
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const context = canvas.getContext("2d")
    if (!context) {
      onStart(riverPoster)
      return
    }

    try {
      context.drawImage(video, 0, 0, canvas.width, canvas.height)
      onStart(canvas.toDataURL("image/jpeg", 0.9))
    } catch {
      onStart(riverPoster)
    }
  }

  return (
    <main className="relative isolate flex h-dvh flex-col items-center overflow-hidden bg-background px-6 text-center text-foreground">
      <img src={riverPoster} alt="" className="absolute inset-0 -z-30 size-full object-cover" />
      <video ref={videoRef} src="/riverbot-assets/river-flow.webm" poster={riverPoster} muted loop playsInline preload="auto" aria-hidden="true" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onError={() => setVideoError(true)} className={`pointer-events-none absolute inset-0 -z-20 size-full object-cover ${videoError ? "hidden" : ""}`} />
      <div className="pointer-events-none absolute inset-0 -z-10 bg-[linear-gradient(180deg,rgba(6,30,24,.28),rgba(6,30,24,.32)_40%,rgba(6,30,24,.85))]" />
      <div className="flex min-h-0 flex-1 max-w-3xl flex-col items-center justify-center py-4 motion-safe:animate-[arrive_1s_ease-out]">
        <div className="w-[clamp(60px,16dvh,160px)] shrink-0 [@media(max-height:600px)]:w-[10dvh] [&>div]:!w-full"><Mascot /></div>
        <p className="mb-[clamp(8px,2dvh,24px)] mt-[clamp(8px,3dvh,28px)] text-[11px] font-medium tracking-[3px] text-[#e5f0d4]">MEET RIVERBOT</p>
        <h1 className="font-display text-[clamp(32px,8.5dvh,82px)] font-semibold leading-[1.15] tracking-[-1px] [@media(max-width:360px)]:text-[38px]">Every river<br />has a story<span className="text-[#d8edac]">.</span></h1>
        <p className="mt-[clamp(8px,2.5dvh,24px)] max-w-sm text-[14px] leading-[1.65] text-[#fffdf0]/85 sm:text-[clamp(14px,2dvh,18px)]">This one can tell you its own.<br />Slow down. Lean in. Follow your curiosity.</p>
        <button onClick={startChat} className="group mt-[clamp(12px,4dvh,36px)] flex min-h-12 shrink-0 items-center gap-5 rounded-full bg-[#d8edac] px-7 text-[15px] font-semibold text-[#234b41] shadow-[0_8px_40px_#08241c30] transition duration-200 hover:-translate-y-1 hover:bg-[#e6f4c7]">{hasConversation ? "Continue chatting" : "Start chatting"}<ArrowRight size={19} className="transition group-hover:translate-x-1" /></button>
        <p className="mt-[clamp(8px,2dvh,20px)] flex items-center gap-2 text-[13px] font-medium text-white/75 sm:text-sm"><Waves size={17} /> A little conversation. A deeper connection.</p>
      </div>
      <div className="flex w-full shrink-0 items-center justify-between gap-5 py-3 sm:px-4 sm:py-5">
        <div className="text-left text-[10px] leading-5 text-white/65"><p>Relational Intelligence<span className="hidden sm:inline"> · Developed at Arizona State University</span></p><p className="text-white/50">River footage: <a href="https://commons.wikimedia.org/wiki/File:Sol_Duc_River_flowing_near_salmon_cascades_2022.webm" target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-white">Sea Cow</a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer" className="hover:text-white">CC BY-SA 4.0</a></p></div>
        {!videoError && <button aria-label={playing ? "Pause river video" : "Play river video"} onClick={() => { if (playing) videoRef.current?.pause(); else videoRef.current?.play().catch(() => setPlaying(false)) }} className="flex size-11 shrink-0 items-center justify-center rounded-full border border-white/30 bg-[#173f32]/30 text-white backdrop-blur-sm transition hover:bg-white/15">{playing ? <Pause size={17} /> : <Play size={17} />}</button>}
      </div>
    </main>
  )
}

function RiverbotApp() {
  const [started, setStarted] = useState(false)
  const [chatBackground, setChatBackground] = useState(riverPoster)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [thinking, setThinking] = useState(false)
  const [modal, setModal] = useState<"about" | "download" | "new" | null>(null)
  const [format, setFormat] = useState<"pdf" | "txt">("pdf")
  const [toast, setToast] = useState("")
  const [voice, setVoice] = useState(false)
  const [muted, setMuted] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState("Ready when you are")
  const [voiceError, setVoiceError] = useState("")
  const [sound, setSound] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<Recognition | null>(null)
  // Bumped on "new conversation"/unmount so a late reply is not shown in the wrong chat
  const convoRef = useRef(0)
  const voiceRef = useRef(false)
  const soundRef = useRef(true)
  const busyRef = useRef(false)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, thinking, started])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(""), 3500)
    return () => clearTimeout(timer)
  }, [toast])
  useEffect(
    () => () => {
      convoRef.current++
      recognitionRef.current?.stop()
      window.speechSynthesis?.cancel()
    },
    [],
  )

  async function send(text: string) {
    const clean = text.trim()
    if (!clean || busyRef.current) {
      inputRef.current?.focus()
      return
    }
    const convo = convoRef.current
    setMessages((current) => [...current, { role: "user", text: clean }])
    setInput("")
    setThinking(true)
    busyRef.current = true
    if (voiceRef.current) setVoiceStatus("Following the current...")

    let answer: string
    try {
      const data = await sendRiverbotMessage(clean)
      answer = replyToText(String(data?.resp ?? "")) || RIVER_ERROR
    } catch (error) {
      console.error("Riverbot request failed:", error)
      answer = RIVER_ERROR
    }
    if (convo !== convoRef.current) return // conversation was reset meanwhile

    setMessages((current) => [...current, { role: "river", text: answer }])
    setThinking(false)
    busyRef.current = false
    if (voiceRef.current && soundRef.current && "speechSynthesis" in window) {
      const speech = new SpeechSynthesisUtterance(answer)
      speech.rate = 0.9
      speech.pitch = 1
      speech.onend = () => {
        if (voiceRef.current) setVoiceStatus("Ready when you are")
      }
      speech.onerror = () => {
        if (voiceRef.current) setVoiceStatus("Ready when you are")
      }
      setVoiceStatus("Riverbot is speaking")
      window.speechSynthesis.speak(speech)
    } else if (voiceRef.current) setVoiceStatus("Ready when you are")
  }

  function listen() {
    if (busyRef.current || muted) return
    window.speechSynthesis?.cancel()
    const browser = window as unknown as {
      SpeechRecognition?: new () => Recognition
      webkitSpeechRecognition?: new () => Recognition
    }
    const SpeechRecognition =
      browser.SpeechRecognition || browser.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setVoiceError(
        "Your browser doesn't support voice input. You can still type below and hear my reply.",
      )
      return
    }
    recognitionRef.current?.stop()
    const recognition = new SpeechRecognition()
    recognitionRef.current = recognition
    recognition.lang = "en-US"
    recognition.continuous = false
    recognition.interimResults = false
    recognition.onresult = (event) => {
      send(event.results[0][0].transcript)
    }
    recognition.onerror = (event) => {
      setVoiceError(
        event.error === "not-allowed"
          ? "Microphone access is off. Allow it in your browser, or type below."
          : "I couldn't hear you clearly. Tap the microphone to try again.",
      )
      setVoiceStatus("Ready when you are")
    }
    recognition.onend = () =>
      setVoiceStatus((current) =>
        current === "I'm listening..." ? "Ready when you are" : current,
      )
    try {
      recognition.start()
      setVoiceError("")
      setVoiceStatus("I'm listening...")
    } catch {
      setVoiceError("The microphone is taking a moment. Please try again.")
    }
  }

  function openVoice() {
    setVoice(true)
    voiceRef.current = true
    setVoiceError("")
    setVoiceStatus(thinking ? "Following the current..." : "Ready when you are")
    setMuted(false)
  }
  function closeVoice() {
    voiceRef.current = false
    setVoice(false)
    recognitionRef.current?.stop()
    window.speechSynthesis?.cancel()
  }
  function newConversation() {
    convoRef.current++
    busyRef.current = false
    setMessages([])
    setThinking(false)
    setInput("")
    setModal(null)
    closeVoice()
  }
  function transcript() {
    return `RIVERBOT - A conversation with the river\n${new Date().toLocaleDateString(undefined, { dateStyle: "long" })}\n${messages.length} messages\n\n${messages.map((message) => `${message.role === "user" ? "You" : "Riverbot"}\n${message.text}`).join("\n\n")}`
  }
  function download() {
    const blob = new Blob(
      [format === "pdf" ? makePdf(transcript()) : transcript()],
      {
        type: format === "pdf" ? "application/pdf" : "text/plain;charset=utf-8",
      },
    )
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = `riverbot-conversation.${format}`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setModal(null)
    setToast("A little piece of the river, saved.")
  }

  if (!started)
    return (
      <SplashScreen
        onStart={(background) => {
          setChatBackground(background)
          setStarted(true)
        }}
        hasConversation={messages.length > 0}
      />
    )

  return (
    <div className="relative isolate flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <img
        src={chatBackground}
        alt="A paused view of the river from the welcome screen"
        className="pointer-events-none absolute inset-0 -z-30 size-full object-cover object-center"
      />
      <div className="pointer-events-none absolute inset-0 -z-20 bg-[linear-gradient(180deg,rgba(9,31,25,.42)_0%,rgba(12,37,29,.29)_30%,rgba(11,40,34,.42)_62%,rgba(9,34,28,.91)_100%)]" />
      <div className="pointer-events-none absolute inset-0 -z-10 bg-[#193e33]/15" />

      <header className="relative z-20 flex shrink-0 items-center justify-between px-5 py-3 sm:px-10 sm:py-4 lg:px-14">
        <button onClick={() => { closeVoice(); setModal(null); setStarted(false) }} className="flex min-h-11 items-center gap-2 rounded-full px-3 text-xs font-medium text-white/85 transition hover:bg-white/10 sm:text-sm" aria-label="Back to home"><Home size={17} strokeWidth={1.6} /><span>Home</span></button>
        <nav
          aria-label="Conversation controls"
          className="flex items-center gap-1 sm:gap-2"
        >
          <button
            onClick={() => setModal("new")}
            className="mr-1 flex min-h-11 items-center gap-2 rounded-full border border-white/20 bg-white/5 px-3 text-xs font-medium backdrop-blur-md transition hover:bg-white/15 sm:px-4 sm:text-[13px]"
          >
            <Plus size={16} />
            <span className="hidden sm:inline">New conversation</span>
            <span className="sm:hidden">New</span>
          </button>
          <IconButton
            label="Download transcript"
            onClick={() => setModal("download")}
          >
            <Download size={19} strokeWidth={1.6} />
          </IconButton>
          <IconButton label="About Riverbot" onClick={() => setModal("about")}>
            <Info size={20} strokeWidth={1.6} />
          </IconButton>
        </nav>
      </header>

      {!voice && (
        <>
          <main className="relative flex min-h-0 flex-1 flex-col">
            {messages.length === 0 ? (
              <section className="min-h-0 flex-1 px-5 text-center motion-safe:animate-[arrive_.8s_ease-out]">
                <div className="flex h-full flex-col items-center justify-center py-2">
                  <div className="mb-[clamp(6px,2dvh,28px)] w-[clamp(50px,16dvh,160px)] shrink-0 [@media(max-height:700px)]:w-[clamp(50px,12dvh,100px)] [@media(max-height:600px)]:!w-[10dvh] [&>div]:!w-full">
                    <Mascot />
                  </div>
                  <h1 className="font-display text-[clamp(28px,5.8dvh,39px)] font-semibold leading-[1.2] tracking-[-1.2px] drop-shadow-sm sm:text-[clamp(32px,7dvh,64px)] [@media(max-width:360px)]:text-[27px]">
                    Hi, I'm Riverbot<span className="text-[#d8edac]">.</span>
                  </h1>
                  <p className="mt-[clamp(6px,1.5dvh,16px)] max-w-[540px] text-[13px] leading-[1.65] text-[#fffdf0]/85 sm:text-[15px] [@media(max-height:600px)]:!text-xs [@media(max-height:600px)]:!leading-normal">
                    I'm a river. A little curious, always flowing,
                    <br className="hidden sm:block" /> and full of stories. What
                    would you like to know?
                  </p>
                  <div className="mt-[clamp(8px,2dvh,32px)] flex items-center gap-3 text-[11px] text-white/65">
                    <span className="h-px w-7 bg-white/25" />
                    <span>Follow your curiosity</span>
                    <span className="h-px w-7 bg-white/25" />
                  </div>
                  <div className="mt-2 grid max-w-[680px] grid-cols-2 justify-center gap-2 sm:flex sm:flex-wrap sm:gap-3">
                    {prompts.map((prompt, index) => (
                      <button
                        key={prompt}
                        onClick={() => send(prompt)}
                        className="flex min-h-11 items-center justify-center gap-2 rounded-full border border-[#f2f0d8]/30 bg-[#eaf0d8]/10 px-3 py-2 text-[11px] font-medium text-[#fffdf0] backdrop-blur-md transition duration-200 hover:-translate-y-1 hover:border-[#d8edac]/70 hover:bg-[#d8edac]/20 sm:px-4 sm:text-[13px]"
                      >
                        {index === 0 ? (
                          <Sparkles size={14} className="text-[#d8edac]" />
                        ) : index === 1 ? (
                          <Leaf size={14} className="text-[#d8edac]" />
                        ) : index === 2 ? (
                          <Waves size={15} className="text-[#d8edac]" />
                        ) : (
                          <span className="text-[#d8edac]">↗</span>
                        )}
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            ) : (
              <section
                aria-label="Conversation"
                aria-live="polite"
                className="mx-auto w-full max-w-[800px] flex-1 overflow-y-auto px-5 pb-6 [scrollbar-width:thin]"
              >
                <div className="mb-7 mt-4 flex items-center justify-center gap-2 text-xs text-[#edf4db]/75">
                  <Waves size={16} /> A little conversation. A deeper
                  connection.
                </div>
                {messages.map((message, index) => (
                  <div
                    key={index}
                    className={`mb-6 flex gap-3 motion-safe:animate-[arrive_.4s_ease-out] ${
                      message.role === "user" ? "justify-end" : "items-start"
                    }`}
                  >
                    {message.role === "river" && <Mascot size="small" />}
                    <div
                      className={`max-w-[88%] px-5 py-4 text-[15px] leading-[1.8] shadow-sm backdrop-blur-xl sm:max-w-[80%] ${
                        message.role === "user"
                          ? "rounded-[25px_25px_6px_25px] border border-white/20 bg-[#f2f2df]/90 text-[#234b41]"
                          : "rounded-[5px_26px_26px_26px] border border-[#b8ded0]/25 bg-[#16483f]/85 text-[#f5f5e9]"
                      }`}
                    >
                      {message.role === "river" && (
                        <div className="mb-1 text-xs font-semibold tracking-wide text-[#d8edac]">
                          Riverbot
                        </div>
                      )}
                      <p className="whitespace-pre-line">{message.text}</p>
                    </div>
                  </div>
                ))}
                {thinking && (
                  <div className="flex items-center gap-3 rounded-full text-sm text-[#ebf1df]">
                    <Mascot size="small" thinking />
                    <Waves size={20} className="motion-safe:animate-pulse" />{" "}
                    Following the current...
                  </div>
                )}
                <div ref={bottomRef} />
              </section>
            )}
          </main>
          <div className="relative mx-auto w-full max-w-[790px] shrink-0 px-5 pb-3 pt-2 sm:pb-4">
            <form
              onSubmit={(event) => {
                event.preventDefault()
                send(input)
              }}
              className="flex items-center gap-2 rounded-[25px] border border-[#e0e9cc]/45 bg-[#f5f6e9]/95 p-2.5 pl-5 text-[#294d41] shadow-[0_8px_40px_#081e2740] transition focus-within:border-[#d8edac] focus-within:ring-4 focus-within:ring-[#d8edac]/15 sm:rounded-full sm:pl-6"
            >
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    send(input)
                  }
                }}
                aria-label="Share a thought with the river"
                placeholder="Let your thoughts flow..."
                className="max-h-24 min-h-8 w-full resize-none bg-transparent py-1.5 text-[15px] leading-6 text-[#294d41] placeholder:text-[#718379] focus:outline-none"
              />
              <button
                type="button"
                onClick={openVoice}
                aria-label="Enter voice mode"
                title="Talk with your voice"
                className="flex size-11 shrink-0 items-center justify-center rounded-full transition hover:bg-[#254c41]/10"
              >
                <Mic size={20} strokeWidth={1.6} />
              </button>
              <span className="h-6 w-px bg-[#234b41]/15" />
              <button
                type="submit"
                disabled={!input.trim() || thinking}
                aria-label="Send message"
                className="flex size-11 shrink-0 items-center justify-center rounded-full bg-[#234e40] text-[#eff5dd] transition hover:bg-[#376a55] disabled:opacity-50"
              >
                <ArrowUp size={21} />
              </button>
            </form>
            <p className="mt-2 flex items-center justify-center gap-1.5 text-[11px] text-white/55">
              <AudioLines size={13} />
              <button
                onClick={openVoice}
                className="transition hover:text-[#d8edac]"
              >
                More of a talker? Try voice mode.
              </button>
            </p>
          </div>
        </>
      )}

      {voice && (
        <main className="relative min-h-0 flex-1 overflow-hidden px-5 text-center motion-safe:animate-[arrive_.5s_ease-out]">
          <div className="flex h-full flex-col items-center justify-center py-[clamp(4px,1.5dvh,16px)]">
            <div className="mb-[clamp(8px,2dvh,24px)] flex items-center gap-2 text-[11px] tracking-[2px] text-[#e3efd4]">
              <AudioLines size={16} /> JUST YOU AND THE RIVER
            </div>
            <div className="relative flex size-[clamp(180px,34dvh,300px)] shrink-0 items-center justify-center">
              {[0, 1, 2].map((index) => (
                <div
                  key={index}
                  className={`pointer-events-none absolute rounded-full border border-[#c4e9d2]/30 ${
                    index === 0
                      ? "inset-0 motion-safe:animate-[ripple_5s_ease-out_infinite]"
                      : index === 1
                        ? "inset-5 motion-safe:animate-[ripple_5s_1.7s_ease-out_infinite]"
                        : "inset-10 motion-safe:animate-[ripple_5s_3.4s_ease-out_infinite]"
                  }`}
                />
              ))}
              <Mascot size="voice" thinking={thinking} />
            </div>
            <h1
              aria-live="polite"
              className="mt-[clamp(10px,2dvh,24px)] font-display text-[clamp(24px,4dvh,30px)] font-medium"
            >
              {voiceStatus}
            </h1>
            <p className="mt-[clamp(4px,1dvh,12px)] text-sm text-[#ecf1df]/70">
              {voiceStatus === "Ready when you are"
                ? "Tap the microphone. Let's follow a thought."
                : "Take your time. I'm not going anywhere."}
            </p>
            {voiceStatus === "Riverbot is speaking" && (
              <div
                className="mt-2 flex h-6 items-center gap-1"
                aria-hidden="true"
              >
                {Array.from({ length: 11 }, (_, index) => (
                  <span
                    key={index}
                    className={`w-1 rounded-full bg-[#cfe8ae] motion-safe:animate-[wave_1s_ease-in-out_infinite] ${
                      index % 3 === 0
                        ? "h-3"
                        : index % 3 === 1
                          ? "h-6 [animation-delay:200ms]"
                          : "h-4 [animation-delay:400ms]"
                    }`}
                  />
                ))}
              </div>
            )}
            {voiceError && (
              <p
                role="alert"
                className="mt-2 max-w-md rounded-2xl bg-[#f4f5ed]/95 p-2 text-sm text-[#234b41]"
              >
                {voiceError}
              </p>
            )}
            <div className="mt-[clamp(10px,2dvh,24px)] flex items-center gap-4">
              <IconButton
                label={muted ? "Unmute microphone" : "Mute microphone"}
                onClick={() => {
                  setMuted(!muted)
                  recognitionRef.current?.stop()
                  setVoiceStatus("Ready when you are")
                }}
                className="border border-white/25 bg-white/10"
              >
                {muted ? <MicOff size={20} /> : <Mic size={20} />}
              </IconButton>
              <button
                onClick={
                  voiceStatus === "I'm listening..."
                    ? () => {
                        recognitionRef.current?.stop()
                        setVoiceStatus("Ready when you are")
                      }
                    : listen
                }
                disabled={muted || thinking}
                aria-label={
                  voiceStatus === "I'm listening..."
                    ? "Stop listening"
                    : "Start listening"
                }
                className="flex size-[clamp(56px,8dvh,64px)] items-center justify-center rounded-full bg-[#d8edac] text-[#234b41] shadow-[0_0_30px_#d8edac30] transition hover:scale-105 disabled:opacity-40"
              >
                <Mic size={26} />
              </button>
              <IconButton
                label="End voice mode"
                onClick={closeVoice}
                className="border border-[#e1ad94]/50 bg-[#b9775b]/70"
              >
                <X size={22} />
              </IconButton>
            </div>
            <div className="mt-[clamp(4px,1dvh,12px)] flex text-xs text-white/70">
              <button
                className="min-h-11"
                onClick={() => {
                  const enabled = !sound
                  setSound(enabled)
                  soundRef.current = enabled
                  if (!enabled) window.speechSynthesis?.cancel()
                }}
              >
                Voice output {sound ? "on" : "off"}
              </button>
            </div>
            <form
              className="mt-[clamp(2px,.5dvh,8px)] flex w-full max-w-md gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                send(input)
              }}
            >
              <input
                aria-label="Type in voice mode"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Or type a thought..."
                className="min-w-0 flex-1 rounded-full border border-white/20 bg-[#123f35]/70 px-4 py-3 text-sm placeholder:text-white/55"
              />
              <button
                disabled={thinking || !input.trim()}
                aria-label="Send typed voice message"
                className="flex size-11 items-center justify-center rounded-full border border-white/20 disabled:opacity-40"
              >
                <ArrowUp size={18} />
              </button>
            </form>
          </div>
        </main>
      )}

      <footer className="flex shrink-0 items-center justify-between gap-4 border-t border-white/10 px-5 py-3 text-[10px] text-white/45 sm:px-10 lg:px-14">
        <span className="flex items-center gap-2">
          <span className="font-display font-semibold text-white/60">
            Relational Intelligence
          </span>
          <span className="hidden sm:inline">·</span>
          <span className="hidden sm:inline">
            Developed at Arizona State University
          </span>
        </span>
        <button
          onClick={() => setModal("about")}
          className="flex items-center gap-1.5 hover:text-white/80"
        >
          <span className="hidden sm:inline">
            A river has a story. Let's listen.
          </span>
          <span className="sm:hidden">About Riverbot</span>
          <Waves size={15} />
        </button>
      </footer>

      {modal === "about" && (
        <Modal title="Meet Riverbot" onClose={() => setModal(null)}>
          <div className="mb-5 flex justify-center">
            <Mascot />
          </div>
          <p className="text-sm leading-7">
            What if a river could tell its own story? Riverbot explores
            relational intelligence—connecting us with the natural world through
            a conversation, rather than just a search.
          </p>
          <p className="mt-4 text-sm leading-7">
            Ask about my past, my relationships, or the possibilities ahead. I'm
            here to invite curiosity and a little care for the world we share.
          </p>
          <p className="mt-5 text-xs font-medium">
            Developed at Arizona State University
          </p>
          <p className="mt-2 text-[10px] text-[#527466]">
            River photography by Maik Astheimer / Unsplash
          </p>
          <p className="mt-2 text-[10px] text-[#527466]">River footage: <a href="https://commons.wikimedia.org/wiki/File:Sol_Duc_River_flowing_near_salmon_cascades_2022.webm" target="_blank" rel="noreferrer" className="underline">Sea Cow / Wikimedia Commons</a> · <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer" className="underline">CC BY-SA 4.0</a>.</p>
          <p className="mt-4 text-[11px] leading-5 text-[#527466]">Voice uses your browser's speech services and may send audio to its provider.</p>
        </Modal>
      )}
      {modal === "new" && (
        <Modal title="A fresh current?" onClose={() => setModal(null)}>
          <p className="text-sm leading-7">
            Start a new conversation with Riverbot? This clears our current
            conversation. You can download it first to keep the memories.
          </p>
          <button
            onClick={newConversation}
            className="mt-6 min-h-12 w-full rounded-full bg-[#234e40] px-4 text-sm font-medium text-[#f4f5ed]"
          >
            Start new conversation
          </button>
          <button
            onClick={() => setModal(null)}
            className="mt-2 min-h-11 w-full rounded-full text-sm hover:bg-[#234b41]/5"
          >
            Keep talking
          </button>
        </Modal>
      )}
      {modal === "download" && (
        <Modal
          title="Take the conversation with you"
          onClose={() => setModal(null)}
        >
          <p className="text-sm leading-7 text-[#527466]">
            Download your conversation with Riverbot.
          </p>
          <div className="my-5 flex items-center gap-3 rounded-2xl bg-[#234b41]/5 p-4">
            <FileText size={24} />
            <div>
              <p className="text-sm font-semibold">
                A conversation with the river
              </p>
              <p className="mt-1 text-xs text-[#527466]">
                {new Date().toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}{" "}
                · {messages.length} messages
              </p>
            </div>
          </div>
          <div className="flex gap-3">
            {(["pdf", "txt"] as const).map((option) => (
              <button
                key={option}
                aria-pressed={format === option}
                onClick={() => setFormat(option)}
                className={`flex min-h-14 flex-1 items-center justify-between rounded-2xl border px-4 text-sm font-semibold ${
                  format === option
                    ? "border-[#234e40] bg-[#deead8]"
                    : "border-[#234b41]/20"
                }`}
              >
                {option.toUpperCase()}
                {format === option && <Check size={18} />}
              </button>
            ))}
          </div>
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(transcript())
                setToast("Conversation copied. Keep the current going.")
              } catch {
                setToast(
                  "Couldn't copy. Try downloading your conversation instead.",
                )
              }
            }}
            className="mt-4 flex min-h-11 w-full items-center justify-center gap-2 text-sm"
          >
            <Copy size={16} /> Copy conversation
          </button>
          <button
            disabled={!messages.length}
            onClick={download}
            className="mt-3 flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-[#234e40] text-sm font-medium text-[#f4f5ed] disabled:opacity-40"
          >
            <Download size={17} /> Download
          </button>
          {!messages.length && (
            <p className="mt-3 text-center text-xs text-[#527466]">
              Start a conversation to collect a little river wisdom.
            </p>
          )}
        </Modal>
      )}
      {toast && (
        <div
          role="status"
          className="fixed bottom-24 left-1/2 z-50 flex w-max max-w-[90vw] -translate-x-1/2 items-center gap-2 rounded-full border border-[#d8edac]/40 bg-[#edf4df] px-5 py-3 text-sm text-[#234b41] shadow-xl"
        >
          <Check size={17} />
          {toast}
        </div>
      )}
    </div>
  )
}

export default function RiverbotPage() {
  return (
    <div className="riverbot-root">
      <RiverbotApp />
    </div>
  )
}
