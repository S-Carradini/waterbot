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
  
  document
    .querySelector(".nav-download")
    .addEventListener("click", async (e) => {
      e.preventDefault();

      try {
        const response = await fetch("/session-transcript", {
          method: "POST",
          credentials: "include", // ✅ ensures cookie/session goes through
        });

        if (!response.ok) {
          throw new Error("Failed to fetch transcript");
        }

        const data = await response.json();

        if (data.presigned_url) {
          // Trigger file download
          const link = document.createElement("a");
          link.href = data.presigned_url;
          link.download = "session-transcript.txt"; // suggest filename
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        }
      } catch (err) {
        console.error("Error downloading transcript:", err);
        alert("Could not download transcript. Please try again.");
      }
    });

  // Home button - navigate to waterbot page
  document
    .querySelector(".nav-item:first-child")
    .addEventListener("click", (e) => {
      e.preventDefault();
      window.location.href = '/waterbot';
    });
  
  // JavaScript to animate open/close on hover
  const navContainer = document.querySelector(".top-right-icon");
  const navItems = document.getElementById("nav-items");

  // height value equals icon height + margins and gaps (64*3 + 8*4)
  const openHeight = "170px";

  navContainer.addEventListener("mouseenter", () => {
    navItems.style.height = openHeight;
    navItems.style.opacity = "1";
    console.log("mouseenter");
  });

  navContainer.addEventListener("mouseleave", () => {
    navItems.style.height = "0";
    navItems.style.opacity = "0";
    console.log("mouseleave");
  });

  function showReactions(message) {
    $(message).find(".reactions").show();
  }

  function hideReactions(message) {
    $(message).find(".reactions").hide();
  }

  function completeRequest() {
    $(".toast").toast("show");
  }

  function submitReaction($clickedReaction) {
    const reactionValue = $clickedReaction.data("reaction");
    console.log("Sending reaction: " + reactionValue);
    const messageID = $clickedReaction.attr("data-messageid");

    if (reactionValue == 0) {
      $("#modal-" + messageID)
        .find(".modal-header >i")
        .removeClass("bi bi-hand-thumbs-up")
        .addClass("bi bi-hand-thumbs-down");

      $("#feedback-" + messageID).css({
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
    const messageID = $clickedReaction
      .parent()
      .parent()
      .find("button.comment")
      .attr("data-messageid");
    var commentInput = $clickedReaction
      .parent()
      .parent()
      .find("#userComment-" + messageID)
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
        $("#modal-" + messageID).modal("toggle");
        $(".card.data-messageid-" + messageID).append(
          thankYouFeedback(messageID)
        );
        scrollToBottom();

        $("#feedback-" + messageID).css({
          display: "none",
        });

        $("[data-messageid]").removeClass("reaction");
        removeThumbsup(messageID);
      });
  }

  function thankYouFeedback(messageID) {
    return `
    <div id="tyfeedback-${messageID}" class="card-footer" style="border-top:0;">
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
 
  $(document).on("click", ".modal-feedback-button", function () {
    $(".modal-feedback-button").removeClass("selected");
    $(this).addClass("selected");
  });

  $(document).on("click", ".feedback-button", function () {
    $(this).addClass("selected");
    var messageID = $(this).attr("data-messageid");
    var commentInput = $(".feedback-button.selected").attr("data-comment");
    if (document.querySelector(".feedback-button") != null) {
      $("#feedback-" + messageID).css({
        display: "none",
      });
      debugger;
      $(".card.data-messageid-" + messageID).append(
        thankYouFeedback(messageID)
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
            <div
                    class="col-auto flex-wrap align-items-center justify-content-center">
                    <img class="waterdrop2" />
                  </div>
                  <div class="col-xs-8 col-sm-8 col-md-8 col-lg-8 col-xl-8 col-8 align-items-center" style="display:inline-flex;">
                    <div class="loader"></div> &nbsp; <span class="text-primary">Generating response...</span>
                  </div>
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
    const apiUrl = `/chat_api`; // Replace with the actual URL if needed

    // Create a request body with the user query
    const requestBody = new FormData();
    requestBody.append("user_query", userQuery);

    fetch(apiUrl, {
      method: "POST",
      body: requestBody,
    })
      .then((response) => response.json())
      .then((botResponse) => {
        // Display the bot's response in the chat
        displayBotMessage(botResponse.resp, botResponse.msgID);
        //typewriter(botResponse);

        //Removing loading animation
        removeLoadingAnimation();
        $("#user_query").prop("disabled", false);
        $("#submit-button").prop("disabled", false);
        //Scroll to bottom function
        scrollToBottom();
      })
      .catch((error) => {
        console.error("Error:", error);
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
    const messageID = $(this).attr("data-messageid");
    const reactionId = $(this).attr("data-reaction");
    // $("#modal-" + messageID).find("button.comment").attr("data-reaction", reactionId);
    if (reactionId == 1)
      $("#feedback-" + messageID).css({
        display: "none",
      });
  });

  $(document).on("click", ".followup-buttons", function () {
    var buttonId = $(this).attr("id");
    switch (buttonId) {
      case "shortButton":
        callAPI("/chat_short_api");
        break;
      case "detailedButton":
        callAPI("/chat_detailed_api");
        break;
      case "actionItemsButton":
        callAPI("/chat_actionItems_api");
        break;
      case "sourcesButton":
        callAPI("/chat_sources_api");
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
    })
      .then((response) => response.json())
      .then((botResponse) => {
        displayBotMessage(botResponse.resp, botResponse.msgID);
        removeLoadingAnimation();
        $("#user_query").prop("disabled", false);
        $("#submit-button").prop("disabled", false);
        scrollToBottom();
      })
      .catch((error) => {
        console.error("Error:", error);
        removeLoadingAnimation();
        $("#user_query").prop("disabled", false);
        $("#submit-button").prop("disabled", false);
        scrollToBottom();
      });
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

function messageInterval(botResponse, messageID) {
  const $el = $(".card-body").find("#botmessage-" + messageID);
  const speed = 20; // ms - faster for character by character
  $el.html(""); // Clear previous content

  // Split by HTML tags and text content
  const parts = botResponse.split(/(<[^>]*>)/g).filter(Boolean);
  let partIndex = 0;
  let charIndex = 0;
  let currentText = "";

  // Display each character sequentially.
  const interval = setInterval(() => {
    if (partIndex >= parts.length) {
      clearInterval(interval); // Stop once all parts are processed
      return;
    }

    const currentPart = parts[partIndex];

    // If it's an HTML tag, add it immediately
    if (currentPart.match(/^<[^>]*>$/)) {
      $el.append(currentPart);
      partIndex++;
      charIndex = 0;
      scrollToBottom()
    } else {
      // If it's text content, add character by character
      if (charIndex < currentPart.length) {
        $el.append(currentPart[charIndex]);
        charIndex++;
        scrollToBottom()
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
function displayBotMessage(botResponse, messageID) {
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
      <div class="row justify-content-start">
        <div class="col-auto d-flex flex-wrap align-items-end justify-content-center">
          <img class="waterdrop1" />
        </div>
        <div class="col-xs-9 col-sm-9 col-md-9 col-lg-9 col-xl-9 col-9 bot-message-body">
          <p class="m-0" id="botmessage-${messageID}"></p>
           <div class="card-footer pt-0 p-8 footer-no-gap " style="padding:8px; border:0;">
      <div class="row mb-0">
        <div class="col-12" style="padding-top: 0.5rem;">
       
        <a class="reaction" title="I like the response" data-messageid=${messageID} data-reaction="1"><i class="bi bi-hand-thumbs-up fa-0.75x"></i></a> 
        <a class="reaction" data-toggle="tooltip" data-placement="top" title="Could be better" data-messageid=${messageID} data-reaction="0"><i class="bi bi-hand-thumbs-down fa-0.75x"></i></a>
        
        <!--  <span class="reaction" data-toggle="tooltip" data-placement="top" title="Could be better" data-bs-toggle="modal" data-messageid=${messageID} data-bs-target="#modal-${messageID}" data-reaction="0"><i class="bi bi-hand-thumbs-down fa-0.75x"></i></span> -->
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
        </div>
        </div>
      </div>
      <div id="feedback-${messageID}" class="row" style="display:none;">
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
                  <button type="button" class="btn btn-sm feedback-other-button fw-bold mb-2" data-bs-toggle="modal" data-messageid=${messageID} data-bs-target="#modal-${messageID}" data-comment="Other" id="btnOther">
                    Other
                  </button>
                  </div>
                </div>
            </div>
        </div>
      </div>
    </div>
      <!-- Modal -->
      <div class="modal fade" id="modal-${messageID}" tabindex="-1" aria-labelledby="exampleModalLabel" aria-hidden="true">
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
                  <textarea placeholder="Provide additional feedback" class="userComment form-control" data-feedback="" id ="userComment-${messageID}"></textarea>
                
            </div>
            <div id="footer-${messageID}" class="modal-footer" data-messageid=${messageID} >
              <button class="comment btn btn-primary btn-new-chat" data-messageid=${messageID} data-user-comment-target=".userComment">Submit</button>                
            </div>
          </div>
        </div>
      </div>
    `;
  chatHistory.appendChild(botMessage);
  messageInterval(botResponse, messageID);
  scrollToBottom();
}

// Timeout Function

const IDLE_MINUTES = 5;
const TARGET_URL = "https://azwaterbot.org";

let idleTimerId, lastActivity;

// const statusEl = document.getElementById("status");

resetIdleTimer();
attachActivityListeners();

function resetIdleTimer() {
  clearTimeout(idleTimerId);
  lastActivity = Date.now();

  idleTimerId = setTimeout(() => {
    window.location.href = TARGET_URL;
  }, IDLE_MINUTES * 60_000);
}

function attachActivityListeners() {
  const events = ["mousemove", "keydown", "scroll", "touchstart"];
  events.forEach((evt) => {
    window.addEventListener(evt, resetIdleTimer, { passive: true });
  });
}
function scrollToBottom() {
    $("#chatbot-prompt").scrollTop(
        $("#chatbot-prompt")[0].scrollHeight -
        $("#chatbot-prompt")[0].clientHeight
    );
}