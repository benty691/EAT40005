const expandedItems = JSON.parse(localStorage.getItem("expandedItems") || "{}");
let previousKeys = [];
let previousEvents = {}; // Track event status to avoid redundant updates

// ─────────────────────────────────────────
// Refresh event per interval
// ─────────────────────────────────────────
async function fetchEvents() {
    const res = await fetch('/events');
    const data = await res.json();
    renderEvents(data);
}

// ─────────────────────────────────────────
// Update or Create new card
// ─────────────────────────────────────────
function renderEvents(events) {
    const container = document.getElementById('log-container');
    const currentKeys = Object.keys(events).sort();
    const newlyAdded = currentKeys.find(k => !previousKeys.includes(k));
    previousKeys = currentKeys;

    currentKeys.forEach(key => {
        const event = events[key];
        const existing = document.getElementById(`card-${key}`);
        const prevStatus = previousEvents[key]?.status;

        if (!existing) {
            const card = createCard(key, event);
            container.appendChild(card);
            if (key === newlyAdded && event.status === 'done') {
                setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'center' }), 300);
            }
        } else if (event.status !== prevStatus) {
            updateCard(key, event); // Only update if status changed
        }

        previousEvents[key] = { status: event.status }; // Cache latest status
    });
}

// ─────────────────────────────────────────
// Create new card on unmatched key 
// ─────────────────────────────────────────
function createCard(key, event) {
    const readable = formatTimestamp(key);
    const safeKey = key.replace(/[:.]/g, "-");
    const card = document.createElement('div');
    card.id = `card-${key}`;
    card.className = 'card';

    const removeBtn = document.createElement('button');
    removeBtn.className = 'btn-remove';
    removeBtn.textContent = 'X';
    removeBtn.onclick = () => removeItem(key);

    const tsDiv = document.createElement('div');
    tsDiv.className = 'timestamp';
    tsDiv.textContent = readable;

    const statusDiv = document.createElement('div');
    statusDiv.className = 'status';

    const actionDiv = document.createElement('div');
    actionDiv.className = 'actions';

    card.appendChild(removeBtn);
    card.appendChild(tsDiv);
    card.appendChild(statusDiv);
    card.appendChild(actionDiv);

    updateCardContent(card, key, event);

    return card;
}

// ─────────────────────────────────────────
// Validate existing card
// ─────────────────────────────────────────
function updateCard(key, event) {
    const card = document.getElementById(`card-${key}`);
    if (card) {
        updateCardContent(card, key, event);
    }
}

// ─────────────────────────────────────────
// Update existing card content
// ─────────────────────────────────────────
function updateCardContent(card, key, event) {
    const statusDiv = card.querySelector('.status');
    const actionDiv = card.querySelector('.actions');
    const safeKey = key.replace(/[:.]/g, "-");

    actionDiv.innerHTML = '';
    if (event.status === 'started') {
        statusDiv.textContent = "Received signal. Data logging started.";
        card.style.backgroundColor = '#780606';
    } else if (event.status === 'processed') {
        statusDiv.textContent = "Data logging finished. Start cleaning process.";
        card.style.backgroundColor = '#2e6930';
    } else if (event.status === 'done') {
        statusDiv.textContent = "Cleaned data saved. Insights is ready.";
        card.style.backgroundColor = '#8a00c2';

        const expandBtn = document.createElement('button');
        expandBtn.className = 'btn-expand';
        expandBtn.textContent = expandedItems[key] ? 'Collapse' : 'Expand';
        expandBtn.onclick = () => toggleExpand(key, expandBtn);

        const expandDiv = document.createElement('div');
        expandDiv.id = `expand-${key}`;
        expandDiv.className = 'expanded-content';
        if (expandedItems[key]) expandDiv.classList.add('show');

        expandDiv.innerHTML = `
            <img src="/plots/heatmap_${safeKey}.png" width="100%">
            <img src="/plots/trend_${safeKey}.png" width="100%">
        `;

        actionDiv.appendChild(expandBtn);
        actionDiv.appendChild(expandDiv);
    }
}

// ─────────────────────────────────────────
// Toggle card expansion
// ─────────────────────────────────────────
function toggleExpand(key, btn) {
    const el = document.getElementById(`expand-${key}`);
    const showing = el.classList.contains('show');
    if (showing) {
        el.classList.remove('show');
        expandedItems[key] = false;
        btn.textContent = 'Expand';
    } else {
        el.classList.add('show');
        expandedItems[key] = true;
        btn.textContent = 'Collapse';
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
    delete previousEvents[key];
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
