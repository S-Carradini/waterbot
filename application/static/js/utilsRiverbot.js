$(document).ready(function () {
  $(".toast").toast("hide");
  $(".waterdrop1").popover("hide");
  var popoverTriggerList = [].slice.call(
    document.querySelectorAll('[data-bs-toggle="popover"]')
  );
  var popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
    return new bootstrap.Popover(popoverTriggerEl);
  });
  var tooltipTriggerList = [].slice.call(
    document.querySelectorAll('[data-toggle="tooltip"]')
  );
  var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
  // // Function to display a user message in the chat interface
  // function displayUserMessage(userQuery) {
  //   const chatHistory = document.getElementById('chatbot-prompt');
  //   const userMessage = document.createElement('div');
  //   userMessage.classList.add('card', 'user-message', 'right');
  //   userMessage.innerHTML = `

  //       <div class="card-body chatbot-question">
  //         <div class="row">
  //           <div class="col-xs-12 col-sm-12 col-md-10 col-lg-10 col-xl-10 col-10 message-body">
  //           ${userQuery}
  //           </div>

  //         </div>
  //       </div>

  //     `;
  //   chatHistory.appendChild(userMessage);
  // }

  // Toggle buttons for language selection
  const englishButton = document.getElementById("english-button");
  const spanishButton = document.getElementById("spanish-button");

  if (englishButton) {
    englishButton.addEventListener("click", function () {
      this.classList.add("active");
      if (spanishButton) {
        spanishButton.classList.remove("active");
      }
      // Navigate to English version if needed
      // window.location.href = 'URL_FOR_ENGLISH_VERSION';
    });
  }

  if (spanishButton) {
    spanishButton.addEventListener("click", function () {
      this.classList.add("active");
      if (englishButton) {
        englishButton.classList.remove("active");
      }
      // Navigate to Spanish version
      window.location.href = "Spanish_Translation_2.0.1.html"; // Adjust the URL as needed when spanish version is developed
    });
  }

  function showReactions(message) {
    $(message).find(".reactions").show();
  }

  function hideReactions(message) {
    $(message).find(".reactions").hide();
  }

  function completeRequest() {
    $(".toast").toast("show");
  }

  function getUniqueDomIdFromCard($element) {
    return $element.closest(".card.bot-message").attr("data-unique-dom-id") || $element.attr("data-messageid");
  }

  function submitReaction($clickedReaction) {
    const reactionValue = $clickedReaction.data("reaction");
    console.log("Sending reaction: " + reactionValue);
    const messageID = $clickedReaction.attr("data-messageid");
    const domId = getUniqueDomIdFromCard($clickedReaction);

    if (reactionValue == 0) {
      $("#modal-" + domId)
        .find(".modal-header >i")
        .removeClass("bi bi-hand-thumbs-up")
        .addClass("bi bi-hand-thumbs-down");

      $("#feedback-" + domId).css({
        display: "flex",
      });
    }

    // Send a POST request with the selected reaction and message
    fetch("/submit_rating_api", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        reaction: reactionValue,
        message_id: messageID,
      }),
    })
      .then((response) => response.text())
      .then((message) => {
        console.log(message); // Handle the response as needed
        $("button.comment[data-messageid=" + messageID + "]").attr(
          "data-reaction",
          reactionValue
        );
      });
  }

  function submitComment($clickedReaction) {
    const reactionValue = $clickedReaction.data("reaction");
    const $modalFooter = $clickedReaction.closest(".modal-footer");
    const messageID = $modalFooter.find("button.comment").attr("data-messageid");
    const domId = getUniqueDomIdFromCard($clickedReaction) || messageID;
    var commentInput = $modalFooter
      .parent()
      .find("#userComment-" + domId)
      .val();
    var selectedFeedback = $(
      document.querySelector(".modal-feedback-button.selected")
    ).attr("data-comment");

    if (selectedFeedback != undefined)
      commentInput = selectedFeedback + ", " + commentInput;

    console.log("Sending comment: " + commentInput + " for " + messageID);
    // Send a POST request with the selected reaction and message
    fetch("/submit_rating_api", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        userComment: commentInput,
        message_id: messageID,
      }),
    })
      .then((response) => response.text())
      .then((message) => {
        console.log(message); // Handle the response as needed
        //Remove one of the reactions

        if (reactionValue == "1") {
          //means thumbs-up
          //remove thumbs-down
          $(
            "span.reaction[data-reaction='0'][data-messageid=" + messageID + "]"
          ).remove();

          //Remove click event from thumbs up
          $(
            "span.reaction[data-reaction='1'][data-messageid=" + messageID + "]"
          ).removeAttr("data-bs-toggle");
          $(
            "span.reaction[data-reaction='1'][data-messageid=" + messageID + "]"
          ).removeAttr("data-bs-target");

          //Replace the icon to fill
          //$("span.reaction[data-reaction='1'][data-messageid="+messageID+"] > i").removeClass("bi-hand-thumbs-up").addClass("bi-hand-thumbs-up-fill");

          $(
            "span.reaction[data-reaction='1'][data-messageid=" +
              messageID +
              "] > i"
          ).addClass("reaction-feedback");

          $(
            "span.reaction[data-reaction='1'][data-messageid=" + messageID + "]"
          ).removeClass("reaction");
        } else {
          //remove thumbs-up
          $(
            "span.reaction[data-reaction='1'][data-messageid=" + messageID + "]"
          ).remove();

          //Remove click event from thumbs up
          $(
            "span.reaction[data-reaction='0'][data-messageid=" + messageID + "]"
          ).removeAttr("data-bs-toggle");
          $(
            "span.reaction[data-reaction='0'][data-messageid=" + messageID + "]"
          ).removeAttr("data-bs-target");

          //Replace the icon to fill
          //$("span.reaction[data-reaction='0'][data-messageid="+messageID+"] > i").removeClass("bi-hand-thumbs-down").addClass("bi-hand-thumbs-down-fill");
          $(
            "span.reaction[data-reaction='0'][data-messageid=" +
              messageID +
              "] > i"
          ).addClass("reaction-feedback");

          $(
            "span.reaction[data-reaction='0'][data-messageid=" + messageID + "]"
          ).removeClass("reaction");
        }

        //Close the modal popup
        $("#modal-" + domId).modal("toggle");
        $clickedReaction.closest(".card.bot-message").append(
          thankYouFeedback(messageID, domId)
        );
        scrollToBottom();

        $("#feedback-" + domId).css({
          display: "none",
        });

        $("[data-messageid]").removeClass("reaction");
        removeThumbsup(messageID);
      });
  }

  function thankYouFeedback(messageID, domId) {
    const idSuffix = domId != null ? domId : messageID;
    return `
    <div id="tyfeedback-${idSuffix}" class="card-footer" style="border-top:0;">
    <div class="row">
      <div class="col-2">
      <img class="waterdrop5" />
      </div>
      <div class="col-10 bot-message-body" style="align-content: center;">
        <span class="feedback-${messageID}" data-messageid="${messageID}">Thanks for your feedback. We will use your feedback to improve the Water Chatbot.</span>     
      </div>
      </div>
    </div>`;
  }
  // Function to display a bot message in the chat interface
  // function displayBotMessage(botResponse, messageID) {
  //   const chatHistory = document.getElementById('chatbot-prompt');
  //   const botMessage = document.createElement('div');
  //   botMessage.classList.add('card', 'left');
  //   botMessage.classList.add('card', 'bot-message', 'data-messageid-' + messageID);
  //   botMessage.innerHTML = `
  //       <div class="card-body welcome-message pb-0" data-messageid=${messageID}>
  //       <div class="row">
  //         <div class="col-xs-12 col-sm-12 col-md-2 col-lg-2 col-xl-2 col-2 d-flex flex-wrap align-items-top justify-content-center">
  //           <img class="waterdrop1" />
  //         </div>
  //         <div class="col-xs-12 col-sm-12 col-md-10 col-lg-10 col-xl-10 col-10 bot-message-body">
  //           <p class="m-0" id="botmessage-${messageID}"></p>
  //         </div>
  //         </div>
  //       </div>
  //       <div class="card-footer pt-0 p-8" style="padding:8px; border:0;">
  //       <div class="row mb-4">
  //         <div class="col-2"></div>
  //         <div class="col-10" style="padding-top: 0.5rem;">

  //         <a class="reaction" title="I like the response" data-messageid=${messageID} data-reaction="1"><i class="bi bi-hand-thumbs-up fa-0.75x"></i></a>
  //         <a class="reaction" data-toggle="tooltip" data-placement="top" title="Could be better" data-messageid=${messageID} data-reaction="0"><i class="bi bi-hand-thumbs-down fa-0.75x"></i></a>

  //         <!--  <span class="reaction" data-toggle="tooltip" data-placement="top" title="Could be better" data-bs-toggle="modal" data-messageid=${messageID} data-bs-target="#modal-${messageID}" data-reaction="0"><i class="bi bi-hand-thumbs-down fa-0.75x"></i></span> -->
  //         <!-- <button type="button" class = "btn btn-sm followup-buttons fw-bold" id="shortButton">
  //           Short
  //         </button>  -->
  //         <a type="button" class = "btn btn-sm followup-buttons fw-bold" id="detailedButton">
  //           Tell me more
  //         </a>
  //         <a type="button" class = "btn btn-sm followup-buttons fw-bold" id="actionItemsButton">
  //           Next steps
  //         </a>
  //         <a type="button" class = "btn btn-sm followup-buttons fw-bold" id="sourcesButton">
  //           Sources
  //         </a>
  //         <!-- <a type="button" class = "btn btn-sm followup-buttons" id="actionItemsButton">
  //           <div>Things you can do</div> -->
  //         </a>
  //         </div>
  //       </div>
  //       <div id="feedback-${messageID}" class="row" style="display:none;">
  //         <div class="col-2"></div>
  //         <div class="col-10">
  //           <div class="row" style="border: 1px solid #ccc;border-radius: 4px">
  //                 <div class="col-3" style="align-self: center;">
  //                     <img class="waterdrop4">
  //                 </div>
  //                 <div class="col-9">
  //                   <div class="card-title m-0"></div>
  //                   <div class="card-body" data-messageid="449">
  //                   <p class="fw-bold">What did you not like?</p>
  //                   <button type="button" class="btn btn-sm feedback-button fw-bold mb-2" data-comment="Factually incorrect" data-messageid=${messageID} id="btnFactuallyIncorrect">
  //                     Factually incorrect
  //                   </button>
  //                   <button type="button" class="btn btn-sm feedback-button fw-bold mb-2" data-comment="Generic response" data-messageid=${messageID} id="btnGenericResponse">
  //                     Generic response
  //                   </button>
  //                   <button type="button" class="btn btn-sm feedback-button fw-bold mb-2" data-comment="Refused to answer" data-messageid=${messageID} id="btnRefusedToAnswer">
  //                     Refused to answer
  //                   </button>
  //                   <button type="button" class="btn btn-sm feedback-other-button fw-bold mb-2" data-bs-toggle="modal" data-messageid=${messageID} data-bs-target="#modal-${messageID}" data-comment="Other" id="btnOther">
  //                     Other
  //                   </button>
  //                   </div>
  //                 </div>
  //             </div>
  //         </div>
  //       </div>
  //     </div>
  //       <!-- Modal -->
  //       <div class="modal fade" id="modal-${messageID}" tabindex="-1" aria-labelledby="exampleModalLabel" aria-hidden="true">
  //         <div class="modal-dialog modal-dialog-centered">
  //           <div class="modal-content">
  //             <div class="modal-header">
  //             <img class="waterdrop3">
  //               <h1 class="modal-title fs-5" id="exampleModalLabel">
  //                 &nbsp;
  //                 Provide additional feedback
  //               </h1>
  //               <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
  //             </div>
  //             <div class="modal-body">

  //                   <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Factually incorrect" id="btnFactuallyIncorrect">
  //                     Factually incorrect
  //                   </button>
  //                   <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Generic response" id="btnGenericResponse">
  //                     Generic response
  //                   </button>
  //                   <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Refused to answer" id="btnRefusedToAnswer">
  //                     Refused to answer
  //                   </button>
  //                   <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Other" id="btnOther">
  //                     Other
  //                   </button>
  //                   <textarea placeholder="Provide additional feedback" class="userComment form-control" data-feedback="" id ="userComment-${messageID}"></textarea>

  //             </div>
  //             <div id="footer-${messageID}" class="modal-footer" data-messageid=${messageID} >
  //               <button class="comment btn btn-primary btn-new-chat" data-messageid=${messageID} data-user-comment-target=".userComment">Submit</button>
  //             </div>
  //           </div>
  //         </div>
  //       </div>
  //     `;
  //   chatHistory.appendChild(botMessage);
  //   messageInterval(botResponse, messageID)
  // }
  $(document).on("click", ".modal-feedback-button", function () {
    $(".modal-feedback-button").removeClass("selected");
    $(this).addClass("selected");
  });

  $(document).on("click", ".feedback-button", function () {
    $(this).addClass("selected");
    var messageID = $(this).attr("data-messageid");
    var domId = getUniqueDomIdFromCard($(this)) || messageID;
    var commentInput = $(".feedback-button.selected").attr("data-comment");
    if (document.querySelector(".feedback-button") != null) {
      $("#feedback-" + domId).css({
        display: "none",
      });
      $(this).closest(".card.bot-message").append(
        thankYouFeedback(messageID, domId)
      );

      fetch("/submit_rating_api", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams({
          userComment: commentInput,
          message_id: messageID,
        }),
      })
        .then((response) => response.text())
        .then((message) => {
          console.log(message); // Handle the response as needed
          //Remove one of the reactions
          removeThumbsUp(messageID);
        });
    }
  });
  $(document).on("click", ".comment", function () {
    submitComment($(this).parent());
  });

  // Function to display a loading animation message in the chat interface
  function displayLoadingAnimation() {
    $("div.loading-animation").remove();
    const chatHistory = document.getElementById("chatbot-prompt");
    const botMessage = document.createElement("div");
    botMessage.classList.add("card", "loading-animation", "left");
    botMessage.innerHTML = `
          <div class="card-body">
            <div class="row">
             <div class="chat-row">
                <img class="waterdrop1" />
              
            <div class="col-md-10 align-items-center" style="display:inline-flex;">
            <div class="loader"></div> &nbsp; <span class="text-primary">Generating response...</span>
            </div>
        </div>
      `;
    chatHistory.appendChild(botMessage);

    //Showing loading animation before the response
    $(".loading-animation").css("display", "flex");
  }

  function removeLoadingAnimation() {
    //Removing loading animation after the response
    $(".loading-animation").css("display", "none");
  }

  // Function to send user queries to the backend and receive responses
  function sendUserQuery(e) {
    const userQuery = document.getElementById("user_query").value;
    e.preventDefault();

    if (userQuery.trim() === "") {
      return; // Don't send empty queries
    }

    // Display the user's message in the chat
    displayUserMessage(userQuery);
    $(".followup-buttons").hide();
    //Start of the loading animation
    displayLoadingAnimation();
    $("#user_query").prop("disabled", true);
    $("#submit-button").prop("disabled", true);

    //Scroll to bottom script
    scrollToBottom();

    // Define the URL of your Flask server
    const apiUrl = `/riverbot_chat_api`; // Riverbot-specific API endpoint

    // Create a request body with the user query
    const requestBody = new FormData();
    requestBody.append("user_query", userQuery);

    fetch(apiUrl, {
      method: "POST",
      body: requestBody,
      credentials: "include", // ✅ Send cookies with request
    })
      .then((response) => response.json())
      .then((botResponse) => {
        // Display the bot's response in the chat; re-enable inputs after typewriter completes
        displayBotMessage(botResponse.resp, botResponse.msgID, function () {
          removeLoadingAnimation();
          $("#user_query").prop("disabled", false);
          $("#submit-button").prop("disabled", false);
          scrollToBottom();
        });
      })
      .catch((error) => {
        console.error("Error:", error);
        window.responseInProgress = false;
        removeLoadingAnimation();
        $("#user_query").prop("disabled", false);
        $("#submit-button").prop("disabled", false);
        scrollToBottom();
      });

    scrollToBottom();

    // Clear the input field after sending the query
    document.getElementById("user_query").value = "";
  }

  $("#user_query").on("keyup", function (e) {
    e.preventDefault();
    if (e.key === "Enter" || e.keyCode === 13) {
      sendUserQuery(e);
    }
  });

  $("#submit-button").on("click", function (e) {
    e.preventDefault();
    sendUserQuery(e);
  });

  $(document).on("mouseover", ".welcome-message", function () {
    showReactions($(this));
  });

  $(document).on("mouseout", ".welcome-message", function () {
    hideReactions($(this));
  });

  // Bind click event to submit the reaction for all elements with the class 'reactions'
  $(document).on("click", ".reaction", function () {
    submitReaction($(this));
    const domId = getUniqueDomIdFromCard($(this));
    const reactionId = $(this).attr("data-reaction");
    // $("#modal-" + domId).find("button.comment").attr("data-reaction", reactionId);
    if (reactionId == 1 && domId)
      $("#feedback-" + domId).css({
        display: "none",
      });
  });

  $(document).on("click", ".followup-buttons", function () {
    if (window.responseInProgress) return;
    var buttonId = $(this).attr("id");
    switch (buttonId) {
      case "shortButton":
        callAPI("/riverbot_chat_short_api");
        break;
      case "detailedButton":
        callAPI("/riverbot_chat_detailed_api");
        break;
      case "actionItemsButton":
        callAPI("/riverbot_chat_actionItems_api");
        break;
      case "sourcesButton":
        callAPI("/riverbot_chat_sources_api");
        break;
      // Add more cases for additional buttons if needed
    }
  });

  function callAPI(apiUrl) {
    console.log("Calling API: " + apiUrl);
    $(".followup-buttons").hide();
    displayLoadingAnimation();
    scrollToBottom();
    fetch(apiUrl, {
      method: "POST",
      credentials: "include", // ✅ Send cookies with request
    })
      .then((response) => {
        if (!response.ok) {
          return response.text().then((errorMessage) => {
            throw new Error(errorMessage);
          });
        }
        return response.json();
      })
      .then((botResponse) => {
        displayBotMessage(botResponse.resp, botResponse.msgID, function () {
          removeLoadingAnimation();
          $("#user_query").prop("disabled", false);
          $("#submit-button").prop("disabled", false);
          scrollToBottom();
        });
      })
      .catch((error) => {
        console.error("Error:", error.message);
        window.responseInProgress = false;
        removeLoadingAnimation();
        $("#user_query").prop("disabled", false);
        $("#submit-button").prop("disabled", false);
        scrollToBottom();
      });
  }

  function scrollToBottom() {
    $("#chatbot-prompt").scrollTop(
      $("#chatbot-prompt")[0].scrollHeight -
        $("#chatbot-prompt")[0].clientHeight
    );
  }

  $(document).on("click", ".reaction", function () {
    $(".reaction").find("i").removeClass("followup-selected");
    if (document.querySelector(".reaction > .followup-selected") != null) {
      $(this).find("i").removeClass("followup-selected");
      //remove active class from thumbs up
      //$(".reaction [data-reaction='0']").find("i").removeClass("active");
    } else {
      $(this).find("i").addClass("followup-selected").css({
        "pointer-events": "none",
      });
      //remove active class from thumbs down
      //$(".reaction [data-reaction='1']").find("i").removeClass("active");
    }
    if ($(this).attr("data-reaction") == 1)
      removeThumbsDown($(this).attr("data-messageid"));
  });
});

function removeThumbsUp(messageid) {
  $("a.reaction[data-messageid='" + messageid + "'][data-reaction=1]")
    .removeClass("reaction")
    .remove();
  $("a[data-messageid='" + messageid + "'][data-reaction=0]").removeClass(
    "reaction"
  );
}

function removeThumbsDown(messageid) {
  $("a.reaction[data-messageid='" + messageid + "'][data-reaction=0]")
    .removeClass("reaction")
    .remove();
  $("a[data-messageid='" + messageid + "'][data-reaction=1]").removeClass(
    "reaction"
  );
}

function messageInterval(botResponse, messageID, onComplete) {
  const $el = $(".card-body").find("#botmessage-" + messageID);
  const speed = 50; // ms - faster for character by character
  $el.html(""); // Clear previous content

  // Split by HTML tags and text content
  const parts = botResponse.split(/(<[^>]*>)/g).filter(Boolean);
  let partIndex = 0;
  let charIndex = 0;

  function finish() {
    if (typeof onComplete === "function") onComplete();
  }

  // Display each character sequentially, handling HTML tags
  const interval = setInterval(() => {
    if (partIndex >= parts.length) {
      clearInterval(interval);
      finish();
      return;
    }

    const currentPart = parts[partIndex];

    // If it's an HTML tag, add it immediately
    if (currentPart.match(/^<[^>]*>$/)) {
      $el.append(currentPart);
      partIndex++;
      charIndex = 0;
    } else {
      // If it's text content, add character by character
      if (charIndex < currentPart.length) {
        $el.append(currentPart[charIndex]);
        charIndex++;
      } else {
        // Move to next part
        partIndex++;
        charIndex = 0;
      }
    }
  }, speed);
}

// Function to display a user message in the chat interface
function displayUserMessage(userQuery) {
  const chatHistory = document.getElementById("chatbot-prompt");
  const userMessage = document.createElement("div");
  userMessage.classList.add("card", "user-message", "right");
  userMessage.innerHTML = `

  <div class="card-body chatbot-question">
    <div class="row">             
      <div class="col-xs-12 col-sm-12 col-md-10 col-lg-10 col-xl-10 col-10 message-body">
      ${userQuery}
      </div>
      
    </div>
  </div>

`;
  chatHistory.appendChild(userMessage);
}

// Function to display a bot message in the chat interface
// onComplete: optional callback invoked when the typewriter effect finishes
function displayBotMessage(botResponse, messageID, onComplete) {
  window.responseInProgress = true;
  window._botMessageDomCounter = (window._botMessageDomCounter || 0) + 1;
  const uniqueDomId = messageID + "-" + window._botMessageDomCounter;
  const chatHistory = document.getElementById("chatbot-prompt");
  const botMessage = document.createElement("div");
  botMessage.classList.add("card", "left");
  botMessage.classList.add(
    "card",
    "bot-message",
    "data-messageid-" + messageID
  );
  botMessage.innerHTML = `
      <div class="card-body welcome-message pb-0" data-messageid=${messageID}>
        <div class = "chat-row">
          <img class="waterdrop1" />
          <div class="col-xs-12 col-sm-12 col-md-10 col-lg-10 col-xl-10 col-10 bot-message-body">
          <p class="m-0" id="botmessage-${uniqueDomId}"></p>
          </div>
        </div>
      </div>
      <div id="reactions-footer-${uniqueDomId}" class="card-footer pt-0 p-8" style="display:none; padding:8px; border:0;">
      <div class="row mb-4">
        <div class="col-11"></div>
        <div class="col-10" style="padding-top: 0.5rem;">
       
        <a class="reaction" title="I like the response" data-messageid=${messageID} data-reaction="1"><i class="bi bi-hand-thumbs-up fa-0.75x"></i></a> 
        <a class="reaction" data-toggle="tooltip" data-placement="top" title="Could be better" data-messageid=${messageID} data-reaction="0"><i class="bi bi-hand-thumbs-down fa-0.75x"></i></a>
        
        <!--  <span class="reaction" data-toggle="tooltip" data-placement="top" title="Could be better" data-bs-toggle="modal" data-messageid=${messageID} data-bs-target="#modal-${uniqueDomId}" data-reaction="0"><i class="bi bi-hand-thumbs-down fa-0.75x"></i></span> -->
        <!-- <button type="button" class = "btn btn-sm followup-buttons fw-bold" id="shortButton">
          Short
        </button>  -->
        <a type="button" class = "btn btn-sm followup-buttons fw-bold" id="detailedButton">
          Tell me more
        </a>
        <a type="button" class = "btn btn-sm followup-buttons fw-bold" id="actionItemsButton">
          Next steps
        </a>
        <a type="button" class = "btn btn-sm followup-buttons fw-bold" id="sourcesButton">
          Sources
        </a>
        <!-- <a type="button" class = "btn btn-sm followup-buttons" id="actionItemsButton">
          <div>Things you can do</div> -->
        </a>
        </div>
      </div>
      <div id="feedback-${uniqueDomId}" class="row" style="display:none;">
        <div class="col-2"></div>
        <div class="col-10">
          <div class="row" style="border: 1px solid #ccc;border-radius: 4px">
                <div class="col-3" style="align-self: center;">
                    <img class="waterdrop4">
                </div>
                <div class="col-9">
                  <div class="card-title m-0"></div>
                  <div class="card-body" data-messageid="449">          
                  <p class="fw-bold">What did you not like?</p>
                  <button type="button" class="btn btn-sm feedback-button fw-bold mb-2" data-comment="Factually incorrect" data-messageid=${messageID} id="btnFactuallyIncorrect">
                    Factually incorrect
                  </button>
                  <button type="button" class="btn btn-sm feedback-button fw-bold mb-2" data-comment="Generic response" data-messageid=${messageID} id="btnGenericResponse">
                    Generic response
                  </button>
                  <button type="button" class="btn btn-sm feedback-button fw-bold mb-2" data-comment="Refused to answer" data-messageid=${messageID} id="btnRefusedToAnswer">
                    Refused to answer
                  </button>
                  <button type="button" class="btn btn-sm feedback-other-button fw-bold mb-2" data-bs-toggle="modal" data-messageid=${messageID} data-bs-target="#modal-${uniqueDomId}" data-comment="Other" id="btnOther">
                    Other
                  </button>
                  </div>
                </div>
            </div>
        </div>
      </div>
      </div>
    </div>
      <!-- Modal -->
      <div class="modal fade" id="modal-${uniqueDomId}" tabindex="-1" aria-labelledby="exampleModalLabel" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
            <img class="waterdrop3">
              <h1 class="modal-title fs-5" id="exampleModalLabel">
                &nbsp;
                Provide additional feedback
              </h1>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
                
                  <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Factually incorrect" id="btnFactuallyIncorrect">
                    Factually incorrect
                  </button>
                  <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Generic response" id="btnGenericResponse">
                    Generic response
                  </button>
                  <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Refused to answer" id="btnRefusedToAnswer">
                    Refused to answer
                  </button>
                  <button type="button" class="btn btn-sm modal-feedback-button fw-bold mb-2" data-messageid=${messageID} data-comment="Other" id="btnOther">
                    Other
                  </button>
                  <textarea placeholder="Provide additional feedback" class="userComment form-control" data-feedback="" id ="userComment-${uniqueDomId}"></textarea>
                
            </div>
            <div id="footer-${uniqueDomId}" class="modal-footer" data-messageid=${messageID} >
              <button class="comment btn btn-primary btn-new-chat" data-messageid=${messageID} data-user-comment-target=".userComment">Submit</button>                
            </div>
          </div>
        </div>
      </div>
    `;
  botMessage.setAttribute("data-unique-dom-id", uniqueDomId);
  chatHistory.appendChild(botMessage);
  messageInterval(botResponse, uniqueDomId, function () {
    window.responseInProgress = false;
    const footer = document.getElementById("reactions-footer-" + uniqueDomId);
    if (footer) footer.style.display = "";
    if (typeof onComplete === "function") onComplete();
  });
}
