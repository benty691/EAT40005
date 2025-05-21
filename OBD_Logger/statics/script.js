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
    // Create card on ts key
    currentKeys.forEach(key => {
        const e = events[key];
        const safeKey = key.replace(/[:.]/g, "-");
        const isExpanded = expandedItems[key] === true;
        const existingCard = document.getElementById(`card-${key}`);
        // Same-key card already exist
        if (!existingCard) {
            // Create new card once
            const div = document.createElement('div');
            div.id = `card-${key}`;
            div.classList.add('card');
            // hh:mm dd/mm/yyyy format ts
            const readable = formatTimestamp(key);
            div.style.backgroundColor = '#ccc';  // default
            // HTML div format
            div.innerHTML = `
                <button class="btn-remove" onclick="removeItem('${key}')">X</button>
                <div class="timestamp">${readable}</div>
                <div class="status"></div>
                <div class="actions"></div>
            `;
            // Components
            const statusDiv = div.querySelector('.status');
            const actionDiv = div.querySelector('.actions');
            // Status changes to div stylings and contents
            if (e.status === 'started') {
                statusDiv.textContent = "Received signal. Data logging started.";
                div.style.backgroundColor = '#780606';
            } else if (e.status === 'processed') {
                statusDiv.textContent = "Data logging finished. Start cleaning process.";
                div.style.backgroundColor = '#2e6930';
            } else if (e.status === 'done') {
                statusDiv.textContent = "Cleaned data saved. Insights is ready.";
                div.style.backgroundColor = '#8a00c2';
                // Expand btn listener
                const expandBtn = document.createElement('button');
                expandBtn.classList.add('btn-expand');
                expandBtn.textContent = "Expand";
                expandBtn.onclick = () => toggleExpand(key);
                actionDiv.appendChild(expandBtn);
                // On expansion
                const expandDiv = document.createElement('div');
                expandDiv.id = `expand-${key}`;
                expandDiv.classList.add('expanded-content');
                if (isExpanded) expandDiv.classList.add('show');
                // Expanded content for plots
                expandDiv.innerHTML = `
                    <img src="/plots/heatmap_${safeKey}.png" width="100%">
                    <img src="/plots/trend_${safeKey}.png" width="100%">
                `;
                actionDiv.appendChild(expandDiv);
            }
            // Final container
            container.appendChild(div);
            // Animation on expansion
            if (key === newlyAdded && e.status === 'done') {
                setTimeout(() => div.scrollIntoView({ behavior: 'smooth', block: 'center' }), 500);
            }
        } else {
            // Update only what's changed
            const statusDiv = existingCard.querySelector('.status');
            const newStatus = e.status === 'done'
                ? "Cleaned data saved. Insights is ready."
                : e.status === 'processed'
                    ? "Data logging finished. Start cleaning process."
                    : "Received signal. Data logging started.";
            // Old key-card must not be re-rendered
            if (statusDiv && statusDiv.textContent !== newStatus) {
                statusDiv.textContent = newStatus;
            }
            // Color changes on status
            const bgColor = e.status === 'done'
                ? '#8a00c2'
                : e.status === 'processed'
                    ? '#2e6930'
                    : '#780606';
            // Fallback colors
            if (existingCard.style.backgroundColor !== bgColor) {
                existingCard.style.backgroundColor = bgColor;
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
