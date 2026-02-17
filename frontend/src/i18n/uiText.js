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
    defaultAnswerText: `For those engaging in vigorous exercise or spending extended time outdoors, drinks with added electrolytes can help replace minerals lost through sweat.

Choosing a hydration drink depends on your activity level and personal needs, but water is always a healthy and reliable choice.

I would love to tell you more! Just click the buttons below or ask a follow-up question.`,
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
