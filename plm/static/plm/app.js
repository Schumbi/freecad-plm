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

  function jobStatusClass(status) {
    if (status === "running") return "job-running";
    if (status === "queued") return "job-queued";
    if (status === "failed") return "job-failed";
    if (status === "succeeded") return "job-succeeded";
    return "";
  }

  function renderExportJobs(panel, payload) {
    var badge = document.getElementById("export-jobs-badge");
    var list = document.getElementById("export-jobs-list");
    if (!badge || !list) return;

    var activeCount = payload.active_count || 0;
    var jobs = payload.jobs || [];
    var hasJobs = jobs.length > 0;

    panel.hidden = !hasJobs;
    badge.hidden = activeCount === 0;
    badge.textContent = String(activeCount);

    list.innerHTML = "";
    jobs.forEach(function (job) {
      var item = document.createElement("li");
      item.className = "export-jobs-item";

      var link = document.createElement("a");
      link.className = "export-jobs-link";
      link.href = job.part_url;
      link.textContent =
        job.project_code +
        " · " +
        job.part_number +
        " · " +
        job.revision_code;

      var meta = document.createElement("span");
      meta.className = "export-jobs-meta";
      meta.textContent = job.job_type_label;

      var status = document.createElement("span");
      status.className =
        "job-status-pill " + jobStatusClass(job.status);
      status.textContent = job.status_label;

      item.appendChild(link);
      item.appendChild(meta);
      item.appendChild(status);

      if (job.error) {
        var error = document.createElement("span");
        error.className = "export-jobs-error";
        error.textContent = job.error;
        item.appendChild(error);
      }

      list.appendChild(item);
    });
  }

  function setupExportJobsPolling() {
    var panel = document.getElementById("export-jobs-panel");
    if (!panel) return;

    var statusUrl = panel.getAttribute("data-export-jobs-status");
    if (!statusUrl) return;

    var timer = null;
    var pollIntervalMs = 8000;

    function scheduleNext(shouldPoll) {
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
      if (!shouldPoll) return;
      timer = window.setTimeout(fetchStatus, pollIntervalMs);
    }

    function fetchStatus() {
      fetch(statusUrl, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("status request failed");
          }
          return response.json();
        })
        .then(function (payload) {
          renderExportJobs(panel, payload);
          scheduleNext(Boolean(payload.poll));
        })
        .catch(function () {
          scheduleNext(true);
        });
    }

    fetchStatus();
  }

  setupDialogs();
  setupActionMenus();
  setupMessages();
  setupListFilters();
  setupSidebarToggle();
  setupExportJobsPolling();
})();
