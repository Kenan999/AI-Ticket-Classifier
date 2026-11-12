// Shoply – frontend.
// The backend connection is added step by step. So far: GET /health, POST /classify,
// POST /review and GET /cases (saved tickets are loaded when the page opens).

// Backend API address. Change it here if the backend runs somewhere else.
const API_BASE_URL = "http://127.0.0.1:8001";

const MIN_MESSAGE_LENGTH = 10;

// Backend status values and how we show them.
const STATUS_HUMAN_REVIEW = "human_review";
const STATUS_REVIEWED = "reviewed";
const STATUS_LABELS = {
  classified: "Classified",
  human_review: "Needs review",
  reviewed: "Manually reviewed",
};

// Name sent to the backend as the reviewer (fixed for now).
const REVIEWER_NAME = "support-agent";

// Categories a reviewer can choose from when correcting a ticket (same names as the backend).
// General = fallback when the backend finds no keyword.
const CATEGORIES = ["Returns", "Shipping", "Billing", "Account", "Technical", "Orders", "General"];

// Development helper: one example ticket per backend category, for the buttons under the form.
const EXAMPLE_TICKETS = [
  { label: "Shipping", text: "Where is my delivery? My package was supposed to arrive three days ago." },
  { label: "Returns", text: "I want a refund, my item arrived damaged and I need to return it." },
  { label: "Billing", text: "My payment failed and my card was charged twice, please check my payment." },
  { label: "Orders", text: "I want to cancel my order, please cancel the purchase." },
  { label: "Account", text: "I cannot log in to my account, I forgot my password." },
  // Unclear text: the backend is unsure, so the ticket lands in Human Review.
  { label: "Human Review", text: "Something is odd, I do not know what to say here." },
];

const state = {
  classified: [],
  review: [],
};

const form = document.getElementById("ticket-form");
const messageInput = document.getElementById("ticket-message");
const errorEl = document.getElementById("form-error");
const successEl = document.getElementById("form-success");
const successDetail = document.getElementById("success-detail");
const classifiedList = document.getElementById("classified-list");
const reviewList = document.getElementById("review-list");
const backendStatus = document.getElementById("backend-status");
const reloadButton = document.getElementById("reload-button");
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
  return toTicket(result);
}

// Turns a ticket from the backend into the shape the dashboard uses.
function toTicket(result) {
  return {
    id: result.ticket_id,
    message: result.text,
    category: result.category,
    confidence: Math.round(result.confidence * 100), // 0.62 -> 62 (%)
    status: result.status,
    customerReply: result.customer_reply, // needed again when the ticket is corrected
  };
}

// GET /cases: loads all saved tickets (newest first) and sorts them into the
// two dashboard lists by status.
async function loadTickets() {
  const cases = await apiRequest("/cases");
  const tickets = cases.map(toTicket);
  state.review = tickets.filter((ticket) => ticket.status === STATUS_HUMAN_REVIEW);
  state.classified = tickets.filter((ticket) => ticket.status !== STATUS_HUMAN_REVIEW);
}

// POST /review: a human confirms ("approve") or changes ("correct") the category.
// A correction needs the new category and the reply text for the customer.
async function sendReview(ticket, newCategory) {
  const body = {
    ticket_id: ticket.id,
    decision: newCategory ? "correct" : "approve",
    reviewer: REVIEWER_NAME,
  };
  if (newCategory) {
    body.final_category = newCategory;
    body.customer_reply = ticket.customerReply;
  }
  await apiRequest("/review", { method: "POST", body: JSON.stringify(body) });
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
  badge.className = ticket.status === STATUS_HUMAN_REVIEW ? "badge badge-review" : "badge badge-pending";
  badge.textContent = STATUS_LABELS[ticket.status] ?? ticket.status;

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

  // Only tickets waiting for a human get the review buttons.
  if (ticket.status === STATUS_HUMAN_REVIEW) {
    card.append(createReviewActions(ticket));
  }

  return card;
}

// Approve = category is right. Correct = category is wrong: a dropdown opens and
// choosing a category sends the correction.
function createReviewActions(ticket) {
  const actions = document.createElement("div");
  actions.className = "review-actions";

  const approve = document.createElement("button");
  approve.type = "button";
  approve.className = "review-btn";
  approve.textContent = "Approve";

  const correct = document.createElement("button");
  correct.type = "button";
  correct.className = "review-btn review-btn-secondary";
  correct.textContent = "Correct";

  const select = document.createElement("select");
  select.className = "review-select";
  select.setAttribute("aria-label", "Choose the correct category");
  select.append(new Option("Choose category…", ""));
  CATEGORIES.forEach((name) => select.append(new Option(name, name)));
  select.hidden = true; // shown after a click on Correct

  const error = document.createElement("p");
  error.className = "ticket-error";
  error.hidden = true;

  const controls = [approve, correct, select];
  approve.addEventListener("click", () => handleReview(ticket, null, controls, error));
  correct.addEventListener("click", () => {
    correct.hidden = true;
    select.hidden = false;
    select.focus();
  });
  select.addEventListener("change", () => {
    if (select.value !== "") handleReview(ticket, select.value, controls, error);
  });

  actions.append(approve, correct, select, error);
  return actions;
}

// Sends the review. newCategory is null for "approve".
async function handleReview(ticket, newCategory, controls, errorEl) {
  errorEl.hidden = true;
  controls.forEach((control) => (control.disabled = true));

  try {
    await sendReview(ticket, newCategory);

    // Reviewed: the ticket leaves Human Review and moves to Classified.
    state.review = state.review.filter((item) => item !== ticket);
    if (newCategory) ticket.category = newCategory;
    ticket.status = STATUS_REVIEWED;
    state.classified.unshift(ticket);
    renderDashboard();
  } catch (error) {
    errorEl.textContent = error.message;
    errorEl.hidden = false;
    controls.forEach((control) => (control.disabled = false));
    controls[2].value = ""; // so the same category can be chosen again
  }
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
  document.getElementById("classified-count").textContent = state.classified.length;
  document.getElementById("review-count").textContent = state.review.length;
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

// On page open: show the empty dashboard, then fill it with the saved tickets.
renderDashboard();
checkBackendHealth();
reloadTickets();

// Loads the saved tickets and shows them. Used on page open and by the Reload button.
async function reloadTickets() {
  reloadButton.disabled = true;
  try {
    await loadTickets();
    renderDashboard();
  } catch (error) {
    // Simple error message in the list if the tickets cannot be loaded.
    renderList(classifiedList, [], error.message);
  } finally {
    reloadButton.disabled = false;
  }
}

reloadButton.addEventListener("click", () => {
  checkBackendHealth();
  reloadTickets();
});
