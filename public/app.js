// Shoply – frontend demo.
// No backend yet: tickets only live in the browser and are lost on reload.
// Classification and human-review routing will come from backend endpoints (phase 2).

const MIN_MESSAGE_LENGTH = 10;
const STATUS_AWAITING = "Awaiting Classification";

// Demo data, only for showing the UI. Clearly marked with demo: true.
// category and confidence (0-100, in percent) will come from the backend in phase 2.
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
  nextTicketNumber: 1001,
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

// --- Ticket submission --------------------------------------------------

// Simulated submission. In phase 2, replace the body with a call to the
// backend, e.g. fetch("/api/tickets", { method: "POST", body: ... }).
async function submitTicket(message) {
  const id = `T-${state.nextTicketNumber++}`;
  return { id, message, status: STATUS_AWAITING, demo: false };
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
  badge.textContent = ticket.demo ? "Demo data" : ticket.status;

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

  const ticket = await submitTicket(message);
  state.classified.unshift(ticket); // newest first
  renderDashboard();

  form.reset();
  successDetail.textContent = `Ticket ${ticket.id} · Status: ${STATUS_AWAITING}`;
  successEl.hidden = false;
});

messageInput.addEventListener("input", () => {
  if (!errorEl.hidden) clearError();
});

renderDashboard();
