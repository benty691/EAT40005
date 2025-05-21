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
    // Create each card on ts keys
    currentKeys.forEach(key => {
        const e = events[key];
        const existing = document.getElementById(`card-${key}`);
        const safeKey = key.replace(/[:.]/g, "-");
        const isExpanded = expandedItems[key] === true;
        // Same key exist, only changed
        if (!existing) {
            const div = document.createElement('div');
            div.id = `card-${key}`;
            div.classList.add('card');
            // Color and message settings
            let bgColor = '#ccc', statusText = 'Pending';
            if (e.status === 'started') {
                bgColor = '#780606';
                statusText = 'Received signal. Data logging started.';
            } else if (e.status === 'processed') {
                bgColor = '#2e6930';
                statusText = 'Data logging finished. Start cleaning process.';
            } else if (e.status === 'done') {
                bgColor = '#8a00c2';
                statusText = 'Cleaned data saved. Insights is ready.';
            }
            // Done element with expand btn and plot block
            div.style.backgroundColor = bgColor;
            div.innerHTML = `
                <button class="btn-remove" onclick="removeItem('${key}')">X</button>
                <div class="timestamp">${formatTimestamp(key)}</div>
                <div class="status">${statusText}</div>
                ${e.status === 'done' ? `
                    <button class="btn-expand" onclick="toggleExpand('${key}')">Expand</button>
                    <div id="expand-${key}" class="expanded-content ${isExpanded ? 'show' : ''}">
                        <img src="/plots/heatmap_${safeKey}.png" width="100%">
                        <img src="/plots/trend_${safeKey}.png" width="100%">
                    </div>` : ''
                }
            `;
            // Append done element with animation
            container.appendChild(div);
            if (e.status === 'done') {
                setTimeout(() => div.scrollIntoView({ behavior: 'smooth', block: 'center' }), 500);
            }
        // Create new dynamically
        } else {
            // Update only status text or color if changed
            const statusEl = existing.querySelector('.status');
            const currentStatus = statusEl?.textContent;
            const newStatus = e.status === 'done' ? "Cleaned data saved. Insights is ready."
                            : e.status === 'processed' ? "Data logging finished. Start cleaning process."
                            : "Received signal. Data logging started.";
            // Change status
            if (currentStatus !== newStatus) {
                statusEl.textContent = newStatus;
                existing.style.backgroundColor =
                    e.status === 'done' ? '#8a00c2' :
                    e.status === 'processed' ? '#2e6930' : '#780606';
            }
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
