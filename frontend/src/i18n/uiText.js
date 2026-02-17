/**
 * Shared EN/ES UI text for chat page localization.
 * Use: uiText[lang].key or uiText.en.headerTitle
 */
export const uiText = {
  en: {
    headerTitle: 'Chat With Blue',
    actionLabels: {
      'tell-me-more': 'Tell Me More',
      'next-steps': 'Next Steps',
      sources: 'Sources',
    },
    defaultAnswerText: `Hi! My name is Blue! I'm here to answer your questions about water in Arizona.
Ask me anything you want about the story of water in our state!
Not sure where to start? You can try asking questions about:

1.Arizona's unique water landscape, rivers, lakes, groundwater, and aquifers
2.Colorado River's role in Arizona's water supply
3.What's on your mind about conserving water in our desert environment?
4.Are there any government programs or initiatives to address drought in Arizona?
Ask any question in the space below to start exploring Arizona's water situation with me!`,
    errorGeneric: 'Sorry, I encountered an error. Please try again.',
    sourcesWarning: 'Sources are available for informational questions. Please ask a specific question.',
    inputPlaceholder: 'Type your question here',
    ariaHome: 'Home',
    ariaDownloadTranscript: 'Download transcript',
    ariaMicrophone: 'Microphone',
    ariaStopRecording: 'Stop Recording',
    downloadErrorAlert: 'Could not download transcript. Please try again.',
    loadingMessage: 'Generating response...',
    feedbackThankYou: 'Thank you for your feedback!',
    feedbackTitle: 'What did you not like?',
    factuallyIncorrect: 'Factually incorrect',
    genericResponse: 'Generic response',
    refusedToAnswer: 'Refused to answer',
    other: 'Other',
    tellUsMore: 'Tell us more...',
    submit: 'Submit',
  },
  es: {
    headerTitle: 'Chatea con Blue',
    actionLabels: {
      'tell-me-more': 'Cuéntame más',
      'next-steps': 'Próximos pasos',
      sources: 'Fuentes',
    },
    defaultAnswerText: `¡Hola! ¡Soy Blue! Estoy aquí para responder tus preguntas sobre el agua en Arizona.
¡Pregúntame lo que quieras sobre la historia del agua en nuestro estado!
¿No sabes por dónde empezar? Puedes intentar preguntar sobre:

1. El paisaje hídrico único de Arizona: ríos, lagos, aguas subterráneas y acuíferos
2. El papel del río Colorado en el suministro de agua de Arizona
3. Qué te gustaría saber sobre conservar el agua en nuestro entorno desértico
4. ¿Existen programas o iniciativas gubernamentales para abordar la sequía en Arizona?
¡Escribe cualquier pregunta en el espacio de abajo para explorar conmigo la situación del agua en Arizona!`,
    errorGeneric: 'Lo siento, hubo un error. Por favor, inténtalo de nuevo.',
    sourcesWarning: 'Las fuentes están disponibles para preguntas informativas. Por favor, haz una pregunta específica.',
    inputPlaceholder: 'Escribe tu pregunta aquí',
    ariaHome: 'Inicio',
    ariaDownloadTranscript: 'Descargar transcripción',
    ariaMicrophone: 'Micrófono',
    ariaStopRecording: 'Detener grabación',
    downloadErrorAlert: 'No se pudo descargar la transcripción. Por favor, inténtalo de nuevo.',
    loadingMessage: 'Generando respuesta...',
    feedbackThankYou: '¡Gracias por tus comentarios!',
    feedbackTitle: '¿Qué no te gustó?',
    factuallyIncorrect: 'Incorrecto',
    genericResponse: 'Respuesta genérica',
    refusedToAnswer: 'Se negó a responder',
    other: 'Otro',
    tellUsMore: 'Cuéntanos más...',
    submit: 'Enviar',
  },
};

export const getActionLabel = (lang, actionType) =>
  (uiText[lang] || uiText.en).actionLabels[actionType] ?? actionType;
