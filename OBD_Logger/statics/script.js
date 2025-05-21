const expandedItems = JSON.parse(localStorage.getItem("expandedItems") || "{}");
let previousKeys = [];

// Listen to event from FastAPI
async function fetchEvents() {
    const res = await fetch('/events');
    const data = await res.json();
    renderEvents(data);
}


// Ensure img filename is in valid format
function sanitizeFilename(ts) {
    return ts.replace(/:/g, '-').replace(/ /g, 'T').replace(/\//g, '-');
}


// Render card changes on event
function renderEvents(events) {
    const container = document.getElementById('log-container');
    const currentKeys = Object.keys(events).sort();
    const newlyAdded = currentKeys.find(key => !previousKeys.includes(key));
    previousKeys = currentKeys;

    currentKeys.forEach(key => {
        const e = events[key];
        const safeKey = key.replace(/[:.]/g, "-");
        const isExpanded = expandedItems[key] === true;
        let card = document.getElementById(`card-${key}`);
        const readable = formatTimestamp(key);

        // New card
        if (!card) {
            card = document.createElement('div');
            card.id = `card-${key}`;
            card.classList.add('card');
            card.style.backgroundColor = '#ccc';

            card.innerHTML = `
                <button class="btn-remove" onclick="removeItem('${key}')">X</button>
                <div class="timestamp">${readable}</div>
                <div class="status"></div>
                <div class="actions"></div>
            `;
            container.appendChild(card);

            if (key === newlyAdded && e.status === 'done') {
                setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'center' }), 300);
            }
        }

        // Update card content
        const statusDiv = card.querySelector('.status');
        const actionsDiv = card.querySelector('.actions');
        const currentStatus = statusDiv.textContent;

        const bgColor = {
            'started': '#780606',
            'processed': '#2e6930',
            'done': '#8a00c2'
        }[e.status] || '#ccc';

        const newStatus = {
            'started': "Received signal. Data logging started.",
            'processed': "Data logging finished. Start cleaning process.",
            'done': "Cleaned data saved. Insights is ready."
        }[e.status] || "Unknown status";

        // Only update if needed
        if (currentStatus !== newStatus) {
            statusDiv.textContent = newStatus;
        }
        if (card.style.backgroundColor !== bgColor) {
            card.style.backgroundColor = bgColor;
        }

        // If now 'done' but not already rendered insight, attach plots
        if (e.status === 'done' && !card.querySelector(`#expand-${key}`)) {
            const expandBtn = document.createElement('button');
            expandBtn.className = 'btn-expand';
            expandBtn.textContent = "Expand";
            expandBtn.onclick = () => toggleExpand(key);
            actionsDiv.appendChild(expandBtn);

            const expandDiv = document.createElement('div');
            expandDiv.id = `expand-${key}`;
            expandDiv.className = 'expanded-content';
            if (isExpanded) expandDiv.classList.add('show');

            expandDiv.innerHTML = `
                <img src="/plots/heatmap_${safeKey}.png" width="100%">
                <img src="/plots/trend_${safeKey}.png" width="100%">
            `;
            actionsDiv.appendChild(expandDiv);
        }
    });
}


// Ensure timestamp name is in hh:mm dd/mm/yyyy
function formatTimestamp(norm_ts) {
    try {
        // Expected input: "2025-05-21T19-50-13-708146"
        // Step 1: Replace the time hyphens with colons
        const parts = norm_ts.split("T");
        if (parts.length !== 2) throw new Error("Invalid format");
        // Split date-time
        const datePart = parts[0]; // "2025-05-21"
        const timePart = parts[1].split("-"); // ["19", "50", "13", "708146"]
        // Check wrong format
        if (timePart.length < 3) throw new Error("Incomplete time");
        // Append new format
        const formatted = `${datePart}T${timePart[0]}:${timePart[1]}:${timePart[2]}`; // "2025-05-21T19:50:13"
        const dt = new Date(formatted);
        if (isNaN(dt.getTime())) throw new Error("Invalid date");
        // Locale for proper string
        const timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const dateStr = dt.toLocaleDateString('en-GB'); // dd/mm/yyyy
        return `${timeStr} ${dateStr}`;
    } catch (err) {
        console.warn("formatTimestamp fallback:", err.message);
        return norm_ts;
    }
}


// Expand dropdown insight element (keep on already expanded key)
function toggleExpand(key) {
    const el = document.getElementById(`expand-${key}`);
    if (!el) return;
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


// Delete item permanently
function removeItem(key) {
    const el = document.getElementById(`expand-${key}`)?.parentElement;
    if (el) el.remove();
    delete expandedItems[key];
    localStorage.setItem("expandedItems", JSON.stringify(expandedItems));
    fetch(`/events/remove/${key}`, { method: 'DELETE' });
}


fetchEvents();
setInterval(fetchEvents, 1000); // Refresh each 1s, less or more if needed
