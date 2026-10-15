// Progressive enhancement only: every page works without it.
//  - A submitted form's button says it is working, so it isn't pressed twice.
//  - A form with unsaved edits asks before the page is left.
//  - After a refused submit, the first field with an error gets focus.
(() => {
  let dirty = null;

  document.addEventListener("input", (event) => {
    const form = event.target.closest("form[data-warn-unsaved]");
    if (form) dirty = form;
  });

  document.addEventListener("submit", (event) => {
    const button = event.submitter;
    dirty = null;
    if (!button || !button.dataset.busy) return;
    // Disable after the browser has read the button's name and value into the request.
    requestAnimationFrame(() => {
      button.dataset.label = button.textContent;
      button.disabled = true;
      button.textContent = button.dataset.busy;
    });
  });

  window.addEventListener("beforeunload", (event) => {
    if (dirty) event.preventDefault();
  });

  window.addEventListener("pageshow", () => {
    document.querySelectorAll("button[data-busy][disabled]").forEach((button) => {
      button.disabled = false;
      button.textContent = button.dataset.label || button.textContent;
    });
  });

  const invalid = document.querySelector('[aria-invalid="true"]');
  if (invalid) invalid.focus();
})();
