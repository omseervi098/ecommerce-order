const $ = (id) => document.getElementById(id);
const money = (cents) => `£${(cents / 100).toFixed(2)}`;

let products = [];
let selectedRef = null;

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const err = new Error(detail?.message || `Request failed (${res.status})`);
    err.detail = detail;
    throw err;
  }
  return body;
}

let bannerTimer;
function showBanner(kind, message, listItems = []) {
  const banner = $("banner");
  banner.className = `banner ${kind}`;
  banner.textContent = message;
  if (listItems.length) {
    const ul = document.createElement("ul");
    listItems.forEach((text) => {
      const li = document.createElement("li");
      li.textContent = text;
      ul.appendChild(li);
    });
    banner.appendChild(ul);
  }
  banner.hidden = false;
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => (banner.hidden = true), kind === "ok" ? 4000 : 8000);
}

function showError(err) {
  const shortages = err.detail?.shortages || [];
  const lines = shortages.map(
    (s) => `${s.name}: requested ${s.requested}, only ${s.available} in stock`
  );
  const message = shortages.length
    ? "Order rejected — not enough stock. Nothing was changed."
    : err.message;
  showBanner("error", message, lines);
}

async function loadProducts() {
  // Remember what the user typed so a refresh doesn't wipe a half-built order.
  const typed = Object.fromEntries(
    [...document.querySelectorAll("#catalogue-body input")].map((i) => [i.dataset.id, i.value])
  );
  products = await api("/api/products");

  const tbody = $("catalogue-body");
  tbody.innerHTML = "";
  for (const p of products) {
    const out = p.stock === 0;
    const tr = document.createElement("tr");
    if (out) tr.className = "out";
    const badge = out
      ? `<span class="badge out">Out of stock</span>`
      : `<span class="badge ${p.stock <= 3 ? "low" : ""} stock">${p.stock}</span>`;
    tr.innerHTML = `
      <td>${escapeHtml(p.name)}<br><small class="muted">${escapeHtml(p.sku)}</small></td>
      <td class="num">${money(p.price_cents)}</td>
      <td>${badge}</td>
      <td><input type="number" min="0" max="${p.stock}" step="1" value="0"
                 data-id="${p.id}" aria-label="Quantity of ${escapeHtml(p.name)}" ${out ? "disabled" : ""}></td>`;
    tbody.appendChild(tr);
    // Set the property, not the attribute, so form.reset() still clears to 0.
    if (!out) tr.querySelector("input").value = typed[p.id] || 0;
  }
  updateTotal();
}

function selectedItems() {
  return [...document.querySelectorAll("#catalogue-body input")]
    .map((input) => ({ product_id: Number(input.dataset.id), qty: Number(input.value) }))
    .filter((item) => Number.isInteger(item.qty) && item.qty > 0);
}

function updateTotal() {
  const total = selectedItems().reduce((sum, item) => {
    const p = products.find((x) => x.id === item.product_id);
    return sum + p.price_cents * item.qty;
  }, 0);
  $("order-total").textContent = money(total);
  $("submit-order").disabled = selectedItems().length === 0;
}

async function submitOrder(event) {
  event.preventDefault();
  const button = $("submit-order");
  button.disabled = true;
  try {
    // The page's stock may be stale; the server re-checks and rejects oversells.
    const order = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({ items: selectedItems() }),
    });
    showBanner("ok", `Order ${order.ref} placed — total ${money(order.total_cents)}.`);
    $("order-form").reset();
    selectedRef = order.ref;
  } catch (err) {
    showError(err);
  }
  await refreshAll();
}

async function loadOrders() {
  const params = new URLSearchParams();
  const q = $("search").value.trim();
  const status = $("status-filter").value;
  if (q) params.set("q", q);
  if (status) params.set("status", status);

  const orders = await api(`/api/orders?${params}`);
  const tbody = $("orders-body");
  tbody.innerHTML = "";
  for (const o of orders) {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    if (o.ref === selectedRef) tr.className = "selected";
    tr.innerHTML = `
      <td><strong>${o.ref}</strong></td>
      <td><span class="badge ${o.status}">${o.status}</span></td>
      <td>${o.item_count}</td>
      <td class="num">${money(o.total_cents)}</td>
      <td><small>${o.created_at}</small></td>`;
    tr.addEventListener("click", () => selectOrder(o.ref));
    tr.addEventListener("keydown", (e) => e.key === "Enter" && selectOrder(o.ref));
    tbody.appendChild(tr);
  }
  $("orders-empty").hidden = orders.length > 0;
}

const ACTION_LABELS = { PACKED: "Mark packed", SHIPPED: "Mark shipped", CANCELLED: "Cancel order" };

async function selectOrder(ref) {
  selectedRef = ref;
  await Promise.all([loadOrders(), loadDetail()]);
}

async function loadDetail() {
  const box = $("order-detail");
  if (!selectedRef) {
    box.hidden = true;
    return;
  }
  let order;
  try {
    order = await api(`/api/orders/${encodeURIComponent(selectedRef)}`);
  } catch (err) {
    box.hidden = true;
    return showError(err);
  }

  const rows = order.items
    .map(
      (i) => `<tr><td>${escapeHtml(i.name)}</td><td class="num">${i.qty}</td>
              <td class="num">${money(i.unit_price_cents)}</td><td class="num">${money(i.line_total_cents)}</td></tr>`
    )
    .join("");

  box.innerHTML = `
    <div class="detail-head">
      <h2>${order.ref}</h2>
      <span class="badge ${order.status}">${order.status}</span>
    </div>
    <table>
      <thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Line total</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td colspan="3"><strong>Total</strong></td><td class="num"><strong>${money(order.total_cents)}</strong></td></tr></tfoot>
    </table>
    <div class="actions"></div>
    ${order.allowed_next.length ? "" : `<p class="muted">This order is ${order.status.toLowerCase()} — no further changes allowed.</p>`}`;

  const actions = box.querySelector(".actions");
  for (const next of order.allowed_next) {
    const btn = document.createElement("button");
    btn.textContent = ACTION_LABELS[next] || next;
    if (next === "CANCELLED") btn.className = "danger";
    btn.addEventListener("click", () => changeStatus(order.ref, next));
    actions.appendChild(btn);
  }
  box.hidden = false;
}

async function changeStatus(ref, status) {
  if (status === "CANCELLED" && !confirm(`Cancel ${ref}? Its stock will be returned.`)) return;
  document.querySelectorAll("#order-detail .actions button").forEach((b) => (b.disabled = true));
  try {
    const order = await api(`/api/orders/${encodeURIComponent(ref)}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    const extra = status === "CANCELLED" ? " Stock has been returned." : "";
    showBanner("ok", `${order.ref} is now ${order.status}.${extra}`);
  } catch (err) {
    showError(err);
  }
  await refreshAll();
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function refreshAll() {
  try {
    await Promise.all([loadProducts(), loadOrders(), loadDetail()]);
  } catch (err) {
    showError(err);
  }
}

let searchTimer;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadOrders().catch(showError), 200);
});
$("status-filter").addEventListener("change", () => loadOrders().catch(showError));
$("catalogue-body").addEventListener("input", updateTotal);
$("order-form").addEventListener("submit", submitOrder);
$("order-form").addEventListener("reset", () => setTimeout(updateTotal));

// Deep link: /#ORD-0003 opens that order's detail.
selectedRef = decodeURIComponent(location.hash.slice(1)) || null;
refreshAll();
