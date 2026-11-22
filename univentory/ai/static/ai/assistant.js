/* Keep the newest assistant answer in view after each question (owner: Jessica's ai module). */
(function () {
  "use strict";
  var bubbles = document.querySelectorAll(".chat .bubble");
  if (bubbles.length > 1) bubbles[bubbles.length - 1].scrollIntoView({ block: "start" });
})();
