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
    // Allow scroll on cards on keys
    const newlyAdded = currentKeys.find(key => !previousKeys.includes(key));
    previousKeys = currentKeys;
    container.innerHTML = '';
    currentKeys.forEach(key => {
        const e = events[key];
        const status = e.status;
        const readable = formatTimestamp(key);
        const div = document.createElement('div');
        div.classList.add('card');
        // Change card status
        if (status === 'started') {
        div.style.backgroundColor = '#780606'; //red
        div.innerHTML = `<button class="btn-remove" onclick="removeItem('${key}')">X</button>
            <div class="timestamp">${readable}</div>
            <div class="status">Received signal. Data logging started.</div>`;
        } else if (status === 'processed') {
        div.style.backgroundColor = '#2e6930'; //green
        div.innerHTML = `<button class="btn-remove" onclick="removeItem('${key}')">X</button>
            <div class="timestamp">${readable}</div>
            <div class="status">Data logging finished. Start cleaning process.</div>`;
        } else if (status === 'done') {
        div.style.backgroundColor = '#8a00c2'; //purple
        const safeKey = key.replace(/[:.]/g, "-"); // Double check on key format, re-sanitizing ts
        const isExpanded = expandedItems[key] === true;
        div.innerHTML = `<button class="btn-remove" onclick="removeItem('${key}')">X</button>
            <div class="timestamp">${readable}</div>
            <div class="status">Cleaned data saved. Insights is ready.</div>
            <button class="btn-expand" onclick="toggleExpand('${key}')">Expand</button>
            <div id="expand-${key}" class="expanded-content ${isExpanded ? 'show' : ''}">
                <img src="/plots/heatmap_${safeKey}.png" width="100%">
                <img src="/plots/trend_${safeKey}.png" width="100%">
            </div>`;
        }
        container.appendChild(div);
        // Scroll to newest
        if (key === newlyAdded && status === 'done') {
            setTimeout(() => div.scrollIntoView({ behavior: 'smooth', block: 'center' }), 500);
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
