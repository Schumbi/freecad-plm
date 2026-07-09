(function () {
  "use strict";

  function closeDialog(dialog) {
    if (!dialog) return;
    dialog.hidden = true;
    document.body.classList.remove("modal-open");
  }

  function openDialog(dialog) {
    if (!dialog) return;
    dialog.hidden = false;
    document.body.classList.add("modal-open");
    var focusable = dialog.querySelector(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
    );
    if (focusable) focusable.focus();
  }

  function setupDialogs() {
    document.addEventListener("click", function (event) {
      var trigger = event.target.closest("[data-dialog-target]");
      if (trigger) {
        event.preventDefault();
        openDialog(document.querySelector(trigger.getAttribute("data-dialog-target")));
        return;
      }

      if (event.target.matches("[data-dialog-close]")) {
        closeDialog(event.target.closest(".plm-dialog"));
        return;
      }

      if (event.target.classList.contains("plm-dialog")) {
        closeDialog(event.target);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeDialog(document.querySelector(".plm-dialog:not([hidden])"));
      }
    });
  }

  function setupActionMenus() {
    document.addEventListener("click", function (event) {
      document.querySelectorAll(".action-menu[open]").forEach(function (menu) {
        if (!menu.contains(event.target)) {
          menu.removeAttribute("open");
        }
      });
    });
  }

  function setupMessages() {
    document.querySelectorAll(".message[data-auto-dismiss]").forEach(function (message) {
      window.setTimeout(function () {
        message.classList.add("is-dismissed");
        window.setTimeout(function () {
          message.remove();
        }, 320);
      }, 5200);
    });

    document.querySelectorAll("[data-message-dismiss]").forEach(function (button) {
      button.addEventListener("click", function () {
        var message = button.closest(".message");
        if (!message) return;
        message.classList.add("is-dismissed");
        window.setTimeout(function () {
          message.remove();
        }, 320);
      });
    });
  }

  function setupListFilters() {
    document.querySelectorAll("[data-filter-input]").forEach(function (input) {
      var list = document.querySelector(input.getAttribute("data-filter-input"));
      if (!list) return;

      input.removeAttribute("disabled");
      input.addEventListener("input", function () {
        var query = input.value.trim().toLowerCase();
        var items = list.querySelectorAll("[data-filter-item]");
        var visible = 0;

        items.forEach(function (item) {
          var haystack = (
            item.getAttribute("data-filter-text") || item.textContent || ""
          ).toLowerCase();
          var matches = !query || haystack.indexOf(query) !== -1;
          item.hidden = !matches;
          if (matches) visible += 1;
        });

        var counter = document.querySelector(
          input.getAttribute("data-filter-count")
        );
        if (counter) {
          counter.textContent = query
            ? visible + " Treffer"
            : counter.getAttribute("data-filter-default") || "";
        }

        var empty = document.querySelector(
          input.getAttribute("data-filter-empty")
        );
        if (empty) {
          empty.hidden = visible !== 0;
        }
      });
    });
  }

  function setupSidebarToggle() {
    var toggle = document.querySelector("[data-sidebar-toggle]");
    var shell = document.querySelector(".app-shell");
    if (!toggle || !shell) return;

    toggle.addEventListener("click", function () {
      shell.classList.toggle("sidebar-collapsed");
    });
  }

  setupDialogs();
  setupActionMenus();
  setupMessages();
  setupListFilters();
  setupSidebarToggle();
})();
