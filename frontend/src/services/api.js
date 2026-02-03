// API service functions for backend communication

const API_BASE_URL = ''; // Use relative URLs for same-origin requests

/**
 * Send a chat message to the backend
 */
export async function sendChatMessage(userQuery, language = 'en') {
  const formData = new FormData();
  formData.append('user_query', userQuery);
  formData.append('language_preference', language);

  try {
    const response = await fetch(`${API_BASE_URL}/chat_api`, {
      method: 'POST',
      body: formData,
      credentials: 'include', // Include cookies for session management
    });

    if (!response.ok) {
      // Try to get error details from response
      let errorMessage = `Failed to send chat message: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.text();
        console.error('Backend error response:', errorData);
        errorMessage += ` - ${errorData}`;
      } catch (e) {
        // Ignore if we can't parse error
      }
      throw new Error(errorMessage);
    }

    return response.json();
  } catch (error) {
    console.error('Error in sendChatMessage:', error);
    throw error;
  }
}

/**
 * Get more detailed response
 */
export async function getDetailedResponse(language = 'en') {
  const formData = new FormData();
  formData.append('language_preference', language);
  try {
    const response = await fetch(`${API_BASE_URL}/chat_detailed_api`, {
      method: 'POST',
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      let errorMessage = `Failed to get detailed response: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.text();
        console.error('Backend error response:', errorData);
        errorMessage += ` - ${errorData}`;
      } catch (e) {
        // Ignore if we can't parse error
      }
      throw new Error(errorMessage);
    }

    return response.json();
  } catch (error) {
    console.error('Error in getDetailedResponse:', error);
    throw error;
  }
}

/**
 * Get action items/next steps
 */
export async function getActionItems(language = 'en') {
  const formData = new FormData();
  formData.append('language_preference', language);
  try {
    const response = await fetch(`${API_BASE_URL}/chat_actionItems_api`, {
      method: 'POST',
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      let errorMessage = `Failed to get action items: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.text();
        console.error('Backend error response:', errorData);
        errorMessage += ` - ${errorData}`;
      } catch (e) {
        // Ignore if we can't parse error
      }
      throw new Error(errorMessage);
    }

    return response.json();
  } catch (error) {
    console.error('Error in getActionItems:', error);
    throw error;
  }
}

/**
 * Get sources
 */
export async function getSources(language = 'en') {
  const formData = new FormData();
  formData.append('language_preference', language);
  try {
    const response = await fetch(`${API_BASE_URL}/chat_sources_api`, {
      method: 'POST',
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      let errorMessage = `Failed to get sources: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.text();
        console.error('Backend error response:', errorData);
        errorMessage += ` - ${errorData}`;
      } catch (e) {
        // Ignore if we can't parse error
      }
      throw new Error(errorMessage);
    }

    return response.json();
  } catch (error) {
    console.error('Error in getSources:', error);
    throw error;
  }
}

/**
 * Submit a rating/reaction
 */
export async function submitRating(messageId, reaction, userComment = null) {
  const formData = new FormData();
  formData.append('message_id', messageId);
  if (reaction !== null) {
    formData.append('reaction', reaction);
  }
  if (userComment) {
    formData.append('userComment', userComment);
  }

  const response = await fetch(`${API_BASE_URL}/submit_rating_api`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to submit rating');
  }

  return response.text();
}

/**
 * Download session transcript
 */
export async function downloadTranscript() {
  const response = await fetch(`${API_BASE_URL}/session-transcript`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to download transcript');
  }

  const data = await response.json();

  if (data.presigned_url) {
    const link = document.createElement('a');
    link.href = data.presigned_url;
    link.download = 'session-transcript.txt';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } else if (data.transcript != null) {
    const blob = new Blob([data.transcript], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = data.filename || 'session-transcript.txt';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  return data;
}

