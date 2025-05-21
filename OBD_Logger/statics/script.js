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
    container.innerHTML = '';
    Object.keys(events).sort().forEach(key => {
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
        div.innerHTML = `<button class="btn-remove" onclick="removeItem('${key}')">X</button>
            <div class="timestamp">${readable}</div>
            <div class="status">Cleaned data saved. Insights is ready.</div>
            <button class="btn-expand" onclick="toggleExpand('${key}')">Expand</button>
            <div id="expand-${key}" class="expanded-content">
            <img src="/plots/heatmap_${safeKey}.png" width="100%">
            <img src="/plots/trend_${safeKey}.png" width="100%">
            </div>`;
        }
        container.appendChild(div);
    });
}


// Ensure timestamp name is in hh:mm dd/mm/yyyy
function formatTimestamp(norm_ts) {
    try {
        const iso = norm_ts.replace("T", " ").replace(/-/g, ":").replace(/(\d+):(\d+):(\d+):/, "$1:$2:$3.");
        const dt = new Date(iso);
        if (isNaN(dt.getTime())) throw new Error("Invalid date");
        return dt.toLocaleTimeString() + ' ' + dt.toLocaleDateString();
    } catch (err) {
        return norm_ts;  // fallback
    }
}


// Expand dropdown insight element
function toggleExpand(key) {
    const el = document.getElementById(`expand-${key}`);
    el.style.display = el.style.display === 'block' ? 'none' : 'block';
}


// Permanently remove item 
function removeItem(key) {
    const el = document.getElementById(`expand-${key}`)?.parentElement;
    if (el) el.remove();
    fetch(`/events/remove/${key}`, { method: 'DELETE' });
}


fetchEvents();
setInterval(fetchEvents, 5000); // Refresh each 5s or less if needed
