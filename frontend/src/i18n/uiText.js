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
    defaultAnswerText: `Para quienes realizan ejercicio intenso o pasan mucho tiempo al aire libre, las bebidas con electrolitos ayudan a reponer los minerales perdidos con el sudor.

Elegir una bebida hidratante depende de tu nivel de actividad y tus necesidades personales, pero el agua siempre es una opción saludable y confiable.

¡Me encantaría contarte más! Solo haz clic en los botones de abajo o haz una pregunta de seguimiento.`,
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
