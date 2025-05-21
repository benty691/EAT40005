const expandedItems = JSON.parse(localStorage.getItem("expandedItems") || "{}");
let previousKeys = [];

async function fetchEvents() {
    const res = await fetch('/events');
    const data = await res.json();
    const container = document.getElementById('log-container');

    const currentKeys = Object.keys(data).sort();
    const newlyAdded = currentKeys.find(key => !previousKeys.includes(key));
    previousKeys = currentKeys;

    currentKeys.forEach(key => {
        const eventData = data[key];
        const cardId = `card-${key}`;
        const existing = document.getElementById(cardId);

        if (!existing) {
            const newCard = createCard(key, eventData);
            container.appendChild(newCard);

            if (key === newlyAdded && eventData.status === 'done') {
                setTimeout(() => newCard.scrollIntoView({ behavior: 'smooth', block: 'center' }), 500);
            }
        } else {
            updateCardStatus(key, eventData);
        }
    });
}


// ─────────────────────────────────────────
// Create a new card for new key
// ─────────────────────────────────────────
function createCard(key, data) {
    const card = document.createElement('div');
    card.id = `card-${key}`;
    card.classList.add('card');

    const safeKey = sanitizeFilename(key);
    const readable = formatTimestamp(key);
    const isExpanded = expandedItems[key];

    // Remove button
    const removeBtn = document.createElement('button');
    removeBtn.classList.add('btn-remove');
    removeBtn.textContent = "X";
    removeBtn.onclick = () => removeItem(key);
    card.appendChild(removeBtn);

    // Timestamp
    const ts = document.createElement('div');
    ts.classList.add('timestamp');
    ts.textContent = readable;
    card.appendChild(ts);

    // Status
    const status = document.createElement('div');
    status.classList.add('status');
    card.appendChild(status);

    // Actions (expand etc.)
    const actions = document.createElement('div');
    actions.classList.add('actions');

    if (data.status === "done") {
        const expandBtn = document.createElement('button');
        expandBtn.classList.add('btn-expand');
        expandBtn.textContent = "Expand";
        expandBtn.onclick = () => toggleExpand(key);
        actions.appendChild(expandBtn);

        const expandDiv = document.createElement('div');
        expandDiv.id = `expand-${key}`;
        expandDiv.classList.add('expanded-content');
        if (isExpanded) expandDiv.classList.add('show');

        expandDiv.innerHTML = `
            <img src="/plots/heatmap_${safeKey}.png" width="100%">
            <img src="/plots/trend_${safeKey}.png" width="100%">
        `;
        actions.appendChild(expandDiv);
    }

    card.appendChild(actions);
    updateCardStatus(key, data); // apply background + text
    return card;
}


// ─────────────────────────────────────────
// Update card status/colors only
// ─────────────────────────────────────────
function updateCardStatus(key, data) {
    const card = document.getElementById(`card-${key}`);
    if (!card) return;

    const status = card.querySelector('.status');
    let statusText = "";
    let color = "#ccc";

    if (data.status === "started") {
        statusText = "Received signal. Data logging started.";
        color = "#780606";
    } else if (data.status === "processed") {
        statusText = "Data logging finished. Start cleaning process.";
        color = "#2e6930";
    } else if (data.status === "done") {
        statusText = "Cleaned data saved. Insights is ready.";
        color = "#8a00c2";
    }

    if (status) status.textContent = statusText;
    card.style.backgroundColor = color;
}


// ─────────────────────────────────────────
// Toggle card expansion
// ─────────────────────────────────────────
function toggleExpand(key) {
    const el = document.getElementById(`expand-${key}`);
    const showing = el.classList.contains('show');
    if (showing) {
        el.classList.remove('show');
        expandedItems[key] = false;
    } else {
        el.classList.add('show');
        expandedItems[key] = true;
    }
    localStorage.setItem("expandedItems", JSON.stringify(expandedItems));
}


// ─────────────────────────────────────────
// Remove a card item
// ─────────────────────────────────────────
function removeItem(key) {
    const card = document.getElementById(`card-${key}`);
    if (card) card.remove();
    delete expandedItems[key];
    localStorage.setItem("expandedItems", JSON.stringify(expandedItems));
    fetch(`/events/remove/${key}`, { method: 'DELETE' });
}


// ─────────────────────────────────────────
// Format timestamp as hh:mm dd/mm/yyyy
// ─────────────────────────────────────────
function formatTimestamp(norm_ts) {
    try {
        const parts = norm_ts.split("T");
        if (parts.length !== 2) throw new Error("Invalid format");
        const datePart = parts[0];
        const timePart = parts[1].split("-");

        if (timePart.length < 3) throw new Error("Incomplete time");
        const formatted = `${datePart}T${timePart[0]}:${timePart[1]}:${timePart[2]}`;
        const dt = new Date(formatted);
        if (isNaN(dt.getTime())) throw new Error("Invalid date");

        const timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const dateStr = dt.toLocaleDateString('en-GB');
        return `${timeStr} ${dateStr}`;
    } catch (err) {
        console.warn("formatTimestamp fallback:", err.message);
        return norm_ts;
    }
}


// ─────────────────────────────────────────
// Sanitize filenames from timestamp
// ─────────────────────────────────────────
function sanitizeFilename(ts) {
    return ts.replace(/:/g, '-').replace(/ /g, 'T').replace(/\//g, '-');
}


// ─────────────────────────────────────────
fetchEvents();
setInterval(fetchEvents, 1000);
