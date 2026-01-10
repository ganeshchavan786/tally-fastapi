// Common JavaScript Functions

const API_BASE = '';

// Toast Notifications
function showToast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
        <span>${message}</span>
    `;
    container.appendChild(toast);
    
    setTimeout(() => toast.remove(), 4000);
}

// API Helper
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: { 'Content-Type': 'application/json' },
            ...options
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Request failed' }));
            throw new Error(error.detail || 'Request failed');
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// Check Tally Status (navbar badge)
async function checkTallyStatus() {
    const badge = document.getElementById('tally-status');
    if (!badge) return;
    
    try {
        const data = await apiCall('/api/health');
        const tallyStatus = data.components?.tally;
        const isConnected = tallyStatus?.status === 'healthy';
        
        if (isConnected) {
            badge.className = 'status-badge online';
            badge.innerHTML = '<span class="dot"></span><span>Tally: Connected</span>';
        } else {
            badge.className = 'status-badge offline';
            badge.innerHTML = '<span class="dot"></span><span>Tally: Disconnected</span>';
        }
    } catch (error) {
        badge.className = 'status-badge offline';
        badge.innerHTML = '<span class="dot"></span><span>Tally: Error</span>';
    }
}

// Format Number
function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

// Format Date
function formatDate(dateStr) {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-IN', { 
        day: '2-digit', 
        month: 'short', 
        year: 'numeric' 
    });
}

// Format Time
function formatTime(dateStr) {
    if (!dateStr) return '--:--';
    const date = new Date(dateStr);
    return date.toLocaleTimeString('en-IN', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

// Format Duration
function formatDuration(seconds) {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    checkTallyStatus();
    setInterval(checkTallyStatus, 30000);
});
