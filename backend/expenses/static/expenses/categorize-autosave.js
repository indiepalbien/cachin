(function() {
  'use strict';

  // Configuration
  const DEBOUNCE_DELAY = 1000; // 1 second for textarea
  const SAVE_TIMEOUT = 10000;   // 10 seconds max per request

  // Get CSRF token from cookie (Django standard)
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  const csrftoken = getCookie('csrftoken');

  // Debounce helper for textarea input
  function debounce(func, delay) {
    let timeoutId;
    return function(...args) {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => func.apply(this, args), delay);
    };
  }

  // Save transaction via AJAX
  async function saveTransaction(formElement, statusElement) {
    const formData = new FormData(formElement);
    const txId = formData.get('tx_id');

    // Show "Guardando..." status
    setStatus(statusElement, 'saving', 'Guardando...');

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), SAVE_TIMEOUT);

      const response = await fetch(formElement.action, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrftoken
        },
        credentials: 'same-origin',
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        throw new Error('Respuesta no JSON del servidor');
      }

      const data = await response.json();

      if (response.ok && data.success) {
        setStatus(statusElement, 'success', 'Guardado!');
        // Hide success message after 2 seconds
        setTimeout(() => setStatus(statusElement, 'idle', ''), 2000);
      } else {
        const errorMsg = data.errors ? data.errors.join(', ') : 'Error al guardar';
        setStatus(statusElement, 'error', errorMsg);
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        setStatus(statusElement, 'error', 'Tiempo de espera agotado');
      } else {
        console.error('Error saving transaction:', error);
        setStatus(statusElement, 'error', 'Error de red. Reintentá.');
      }
    }
  }

  // Set status message with styling
  function setStatus(element, state, message) {
    element.textContent = message;
    element.className = 'save-status save-status-' + state;
    element.setAttribute('aria-live', 'polite');
  }

  // Track pending saves to prevent concurrent saves on same transaction
  const pendingSaves = new Map();

  // Initialize auto-save for all transaction forms
  function initAutoSave() {
    const forms = document.querySelectorAll('form[id^="tx-"]');

    forms.forEach(form => {
      const txId = form.querySelector('input[name="tx_id"]').value;
      const categorySelect = form.querySelector('select[name="category_id"]');
      const commentsTextarea = form.querySelector('textarea[name="comments"]');
      const submitButton = form.querySelector('button[type="submit"]');

      // Create status element
      const statusDiv = document.createElement('div');
      statusDiv.className = 'save-status save-status-idle';
      statusDiv.setAttribute('role', 'status');
      statusDiv.setAttribute('aria-live', 'polite');

      // Insert status after submit button
      submitButton.parentNode.insertBefore(statusDiv, submitButton.nextSibling);

      // Hide submit button (keep for fallback, but hide with CSS)
      submitButton.style.display = 'none';

      // Category dropdown - immediate save on change
      categorySelect.addEventListener('change', () => {
        // Cancel pending save if exists
        if (pendingSaves.has(txId)) {
          clearTimeout(pendingSaves.get(txId));
        }
        saveTransaction(form, statusDiv);
      });

      // Comments textarea - debounced save
      const debouncedSave = debounce(() => {
        saveTransaction(form, statusDiv);
      }, DEBOUNCE_DELAY);

      commentsTextarea.addEventListener('input', () => {
        // Show "typing..." indicator
        setStatus(statusDiv, 'typing', 'Escribiendo...');
        debouncedSave();
      });

      // Prevent form submission (keep as fallback, but prevent default)
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        saveTransaction(form, statusDiv);
      });
    });
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAutoSave);
  } else {
    initAutoSave();
  }
})();
