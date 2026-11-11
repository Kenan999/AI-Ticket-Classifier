// Shoply – frontend.
// The backend connection is added step by step. So far: GET /health and POST /classify.
// Tickets are kept in the browser only and are gone after a reload.

// Backend API address. Change it here if the backend runs somewhere else.
const API_BASE_URL = "http://127.0.0.1:8001";

const MIN_MESSAGE_LENGTH = 10;

// Backend status values and how we show them.
const STATUS_HUMAN_REVIEW = "human_review";
const STATUS_LABELS = {
  classified: "Classified",
  human_review: "Needs review",
};

// Development helper: one example ticket per MVP category, for the buttons under the form.
const EXAMPLE_TICKETS = [
  { label: "Delivery", text: "Where is my delivery? My package was supposed to arrive three days ago." },
  { label: "Refund", text: "I want a refund, my item arrived damaged and I need to return it." },
  { label: "Payment", text: "My payment failed and my card was charged twice, please check my payment." },
  { label: "Order", text: "I want to change my order, I ordered the wrong size." },
  { label: "Account", text: "I cannot log in to my account, I forgot my password." },
];

// Demo data, only for showing the UI. Clearly marked with demo: true.
// Confidence is shown in percent (0-100).
const demoReview = [
  {
    id: "DEMO-3",
    message: "I am not sure what happened, but something is wrong with my account.",
    category: "Account",
    confidence: 62,
    demo: true,
  },
];

const state = {
  classified: [],
  review: [...demoReview],
};

const form = document.getElementById("ticket-form");
const messageInput = document.getElementById("ticket-message");
const errorEl = document.getElementById("form-error");
const successEl = document.getElementById("form-success");
const successDetail = document.getElementById("success-detail");
const classifiedList = document.getElementById("classified-list");
const reviewList = document.getElementById("review-list");
const backendStatus = document.getElementById("backend-status");
const submitButton = form.querySelector("button[type=submit]");
const submitLabel = submitButton.textContent;

// --- Backend API ----------------------------------------------------------

// One place for all backend requests. Returns the JSON answer, or throws an
// Error with a short message that is safe to show to the user.
async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: options.body ? { "Content-Type": "application/json" } : {},
      ...options,
    });
  } catch {
    throw new Error("Backend not reachable. Please try again later.");
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    // The answer had no JSON body.
  }

  if (!response.ok) {
    // The backend sends errors as { error: { code, message } }.
    throw new Error(data?.error?.message ?? `Request failed (${response.status}).`);
  }
  return data;
}

// GET /health: shows in the dashboard header whether the backend is available.
async function checkBackendHealth() {
  try {
    await apiRequest("/health");
    setBackendStatus("online", "Backend online");
  } catch {
    setBackendStatus("offline", "Backend offline");
  }
}

function setBackendStatus(state, text) {
  backendStatus.dataset.state = state;
  backendStatus.textContent = text;
}

// --- Ticket submission --------------------------------------------------

// POST /classify: sends the ticket text to the backend. The backend creates the
// ticket id and answers with category, confidence (0-1) and status.
async function submitTicket(message) {
  const result = await apiRequest("/classify", {
    method: "POST",
    body: JSON.stringify({ text: message }),
  });

  return {
    id: result.ticket_id,
    message: result.text,
    category: result.category,
    confidence: Math.round(result.confidence * 100), // 0.62 -> 62 (%)
    status: result.status,
    demo: false,
  };
}

// --- Rendering ------------------------------------------------------------

// Small chip like "Category: Account". Without a value it shows a dashed placeholder.
function createChip(label, value) {
  const chip = document.createElement("span");
  chip.className = value == null ? "chip chip-empty" : "chip";
  chip.textContent = `${label}: ${value ?? "–"}`;
  return chip;
}

function createTicketCard(ticket) {
  const card = document.createElement("li");
  card.className = "ticket";

  const head = document.createElement("div");
  head.className = "ticket-head";

  const id = document.createElement("span");
  id.className = "ticket-id";
  id.textContent = ticket.id;

  const badge = document.createElement("span");
  badge.className = ticket.demo ? "badge badge-demo" : "badge badge-pending";
  badge.textContent = ticket.demo ? "Demo data" : (STATUS_LABELS[ticket.status] ?? ticket.status);

  const category = createChip("Category", ticket.category);
  const confidence = createChip("Confidence", ticket.confidence == null ? null : `${ticket.confidence}%`);

  // Chips sit on the right side of the header row to keep the card short.
  const chips = document.createElement("div");
  chips.className = "ticket-chips";
  chips.append(category, confidence, badge);

  head.append(id, chips);

  // textContent (not innerHTML) so user input is never run as HTML.
  const message = document.createElement("p");
  message.className = "ticket-message";
  message.textContent = ticket.message;

  card.append(head, message);

  return card;
}

function renderList(listEl, tickets, emptyText) {
  listEl.replaceChildren();

  if (tickets.length === 0) {
    const empty = document.createElement("li");
    empty.className = "ticket-empty";
    empty.textContent = emptyText;
    listEl.append(empty);
    return;
  }

  tickets.forEach((ticket) => listEl.append(createTicketCard(ticket)));
}

function renderDashboard() {
  renderList(classifiedList, state.classified, "No tickets yet. New tickets will show up here.");
  renderList(reviewList, state.review, "No tickets need review.");
}

// --- Form handling --------------------------------------------------------

function showError(text) {
  errorEl.textContent = text;
  errorEl.hidden = false;
  successEl.hidden = true;
  messageInput.setAttribute("aria-invalid", "true");
}

function clearError() {
  errorEl.hidden = true;
  messageInput.removeAttribute("aria-invalid");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = messageInput.value.trim();

  if (message.length === 0) {
    showError("Please describe your issue before submitting.");
    return;
  }
  if (message.length < MIN_MESSAGE_LENGTH) {
    showError(`Please write at least ${MIN_MESSAGE_LENGTH} characters.`);
    return;
  }

  clearError();
  successEl.hidden = true;

  // Loading state: the button is blocked until the backend has answered.
  submitButton.disabled = true;
  submitButton.textContent = "Sending…";

  try {
    const ticket = await submitTicket(message);

    // The backend decides where the ticket belongs. Newest first.
    const list = ticket.status === STATUS_HUMAN_REVIEW ? state.review : state.classified;
    list.unshift(ticket);
    renderDashboard();

    form.reset();
    successDetail.textContent = `Ticket ${ticket.id}`;
    successEl.hidden = false;
  } catch (error) {
    showError(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = submitLabel;
  }
});

messageInput.addEventListener("input", () => {
  if (!errorEl.hidden) clearError();
});

// Example buttons: put the example text into the field, the user sends it.
const exampleButtons = document.getElementById("example-buttons");
EXAMPLE_TICKETS.forEach((example) => {
  const button = document.createElement("button");
  button.type = "button"; // must not submit the form
  button.className = "example-btn";
  button.textContent = example.label;
  button.title = example.text;
  button.addEventListener("click", () => {
    messageInput.value = example.text;
    clearError();
    successEl.hidden = true;
    messageInput.focus();
  });
  exampleButtons.append(button);
});

renderDashboard();
checkBackendHealth();
