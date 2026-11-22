/*
 * Classification suggestion widget (owner: Jessica's ai module, AI-01/AI-02).
 * Mounted into the asset editor's [data-mount="classification"] element.
 * It only proposes a category; the custodian applies it and saves the form.
 * Without JavaScript the manual fields still work.
 */
(function () {
  "use strict";
  var mount = document.querySelector('[data-mount="classification"][data-endpoint]');
  if (!mount) return;
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }
  mount.innerHTML = "";
  var intro = el("p", "small muted", "Get a category suggestion from the title and description. You review it; nothing is saved until you save the asset.");
  var button = el("button", "btn btn-secondary btn-sm", "Suggest a category");
  button.type = "button";
  var out = el("div", "mt-4");
  out.setAttribute("aria-live", "polite");
  mount.appendChild(intro);
  mount.appendChild(button);
  mount.appendChild(out);

  button.addEventListener("click", function () {
    var title = (document.getElementById("id_title") || {}).value || "";
    var description = (document.getElementById("id_description") || {}).value || "";
    var body = new URLSearchParams({ title: title, description: description });
    out.textContent = "Checking...";
    fetch(mount.getAttribute("data-endpoint"), {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString()
    }).then(function (r) { return r.json(); }).then(function (data) {
      out.innerHTML = "";
      if (!data.category_id) {
        out.appendChild(el("p", "small", data.message || "No suggestion. Choose a category manually."));
        return;
      }
      var line = el("p", "mb-2");
      line.appendChild(document.createTextNode("Suggested: "));
      line.appendChild(el("strong", "", data.category_name));
      out.appendChild(line);
      var status = data.status === "SUFFICIENT_EVIDENCE" ? "Sufficient evidence" : "Needs review";
      out.appendChild(el("p", "small muted mb-2", status + ". Matched words: " + data.evidence.join(", ") + "."));
      out.appendChild(el("p", "xsmall faint", data.message));
      var apply = el("button", "btn btn-primary btn-sm", "Use this category");
      apply.type = "button";
      apply.addEventListener("click", function () {
        var select = document.querySelector("[data-category-select]");
        if (select) {
          select.value = String(data.category_id);
          select.dispatchEvent(new Event("change"));
          select.focus();
        }
        apply.textContent = "Applied. Review and save the form.";
        apply.disabled = true;
      });
      out.appendChild(apply);
    }).catch(function () {
      out.textContent = "Suggestions are unavailable right now. Choose the category manually.";
    });
  });
})();
