// Sync Page JavaScript

let selectedCompanies = [];
let syncInterval = null;
let companyPeriods = {}; // Store period for each company
let autoSyncTimer = null;
let syncIntervalMinutes = 60; // Default 1 hour

// Tab Switching
function switchTab(tabName) {
    // Remove active from all tabs
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    // Activate selected tab
    document.querySelector(`[onclick="switchTab('${tabName}')"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
    
    // Load tab-specific data
    if (tabName === 'tally-config') {
        loadTallyConfig();
    }
}

// Load Companies - Show all companies from Tally with sync status
async function loadCompanies() {
    const list = document.getElementById('company-list');
    list.innerHTML = '<div class="loading"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';
    
    try {
        const data = await apiCall('/api/companies');
        
        // Get synced companies from database (correct endpoint)
        const syncedCompanies = await apiCall('/api/data/synced-companies').catch(() => ({ companies: [] }));
        const syncedNames = (syncedCompanies.companies || []).map(c => c.company_name || c.name || c);
        
        if (!data.companies || data.companies.length === 0) {
            list.innerHTML = '<div class="empty-state"><i class="fas fa-building"></i><p>No companies found in Tally. Make sure Tally is running.</p></div>';
            return;
        }
        
        // Filter out synced companies - only show NEW companies
        const newCompanies = data.companies.filter(c => !syncedNames.includes(c.name));
        
        if (newCompanies.length === 0) {
            list.innerHTML = '<div class="empty-state"><i class="fas fa-check-circle"></i><p>All companies are already synced!</p><p class="text-muted">Go to Dashboard to view synced data</p></div>';
            return;
        }
        
        list.innerHTML = newCompanies.map(company => {
            // Extract period from company name or use Tally data
            // Company names often have period like "MATOSHRI ENTERPRISES 18-24" meaning 2018-2024
            const extractedPeriod = extractPeriodFromName(company.name);
            const fromDate = parseTallyDate(company.books_from) || extractedPeriod.from || '2025-04-01';
            const toDate = parseTallyDate(company.books_to) || extractedPeriod.to || '2026-03-31';
            companyPeriods[company.name] = { from: fromDate, to: toDate };
            
            return `
                <div class="company-item" data-company="${company.name}">
                    <div class="company-checkbox" onclick="toggleCompany('${company.name}')">
                        <i class="fas fa-check"></i>
                    </div>
                    <div class="company-info" onclick="toggleCompany('${company.name}')">
                        <div class="company-name-row">
                            <span class="company-name">${company.name}</span>
                            <span class="not-synced-badge">New</span>
                        </div>
                        <div class="company-period">
                            <span class="period-display" id="period-${company.name.replace(/[^a-zA-Z0-9]/g, '_')}">
                                ${formatDateDisplay(fromDate)} - ${formatDateDisplay(toDate)}
                            </span>
                        </div>
                    </div>
                    <div class="company-actions">
                        <button class="btn btn-sm btn-outline" onclick="editPeriod('${company.name}')" title="Edit Period">
                            <i class="fas fa-pencil-alt"></i>
                        </button>
                        <button class="btn btn-sm btn-primary" onclick="syncCompany('${company.name}')" title="Full Sync">
                            <i class="fas fa-sync"></i> Sync
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        list.innerHTML = `<div class="empty-state"><i class="fas fa-exclamation-triangle"></i><p>Error: ${error.message}</p></div>`;
    }
}

// Extract period from company name pattern like "MATOSHRI ENTERPRISES 18-24" or "Company 25-26"
// DEVELOPER NOTE: Many Tally companies have financial year in name (e.g., "18-24" means Apr 2018 to Mar 2024)
function extractPeriodFromName(companyName) {
    // Pattern: Look for YY-YY at end of name (e.g., "18-24", "25-26")
    const yearPattern = /(\d{2})-(\d{2})$/;
    const match = companyName.match(yearPattern);
    
    if (match) {
        const startYear = parseInt(match[1]);
        const endYear = parseInt(match[2]);
        
        // Convert 2-digit year to 4-digit (18 -> 2018, 25 -> 2025)
        const fullStartYear = startYear > 50 ? 1900 + startYear : 2000 + startYear;
        const fullEndYear = endYear > 50 ? 1900 + endYear : 2000 + endYear;
        
        // Financial year: Apr 1 to Mar 31
        return {
            from: `${fullStartYear}-04-01`,
            to: `${fullEndYear}-03-31`
        };
    }
    
    // Pattern: Look for "(from 1-Sep-25)" style
    const fromPattern = /\(from\s+(\d{1,2})-([A-Za-z]{3})-(\d{2})\)/i;
    const fromMatch = companyName.match(fromPattern);
    
    if (fromMatch) {
        const day = fromMatch[1].padStart(2, '0');
        const monthStr = fromMatch[2];
        const year = parseInt(fromMatch[3]) > 50 ? 1900 + parseInt(fromMatch[3]) : 2000 + parseInt(fromMatch[3]);
        
        const months = { 'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                         'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12' };
        const month = months[monthStr.charAt(0).toUpperCase() + monthStr.slice(1).toLowerCase()] || '04';
        
        return {
            from: `${year}-${month}-${day}`,
            to: `${year + 1}-03-31`
        };
    }
    
    return { from: null, to: null };
}

// Parse Tally date format (e.g., "1-Apr-18 to 31-Mar-26" or "1-Apr-2025")
function parseTallyDate(dateStr) {
    if (!dateStr) return null;
    
    // Handle format like "1-Apr-25 to 31-Mar-26" - extract just the date part
    const cleanDate = dateStr.split(' to ')[0].trim();
    
    // Parse formats: "1-Apr-25", "01-Apr-2025", "1-Apr-2025"
    const parts = cleanDate.split('-');
    if (parts.length !== 3) return null;
    
    const day = parts[0].padStart(2, '0');
    const monthStr = parts[1];
    const yearStr = parts[2];
    
    const months = { 'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                     'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12' };
    
    const month = months[monthStr] || '01';
    const year = yearStr.length === 2 ? (parseInt(yearStr) > 50 ? '19' + yearStr : '20' + yearStr) : yearStr;
    
    return `${year}-${month}-${day}`;
}

// Format date for display
function formatDateDisplay(dateStr) {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    return date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

// Toggle Company Selection
function toggleCompany(name) {
    const items = document.querySelectorAll('.company-item');
    items.forEach(item => {
        if (item.querySelector('.company-name').textContent === name) {
            item.classList.toggle('selected');
            if (item.classList.contains('selected')) {
                if (!selectedCompanies.includes(name)) selectedCompanies.push(name);
            } else {
                selectedCompanies = selectedCompanies.filter(c => c !== name);
            }
        }
    });
}

// Refresh Companies
function refreshCompanies() {
    loadCompanies();
}

// Edit Period for a company (Task 2 - pencil button)
function editPeriod(companyName) {
    const period = companyPeriods[companyName] || { from: '2025-04-01', to: new Date().toISOString().split('T')[0] };
    
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3>Edit Period - ${companyName}</h3>
                <button class="btn-close" onclick="this.closest('.modal-overlay').remove()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="date-input">
                    <label>From Date</label>
                    <input type="date" id="edit-from-date" value="${period.from}">
                </div>
                <div class="date-input">
                    <label>To Date</label>
                    <input type="date" id="edit-to-date" value="${period.to}">
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-outline" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
                <button class="btn btn-primary" onclick="savePeriod('${companyName}')">Save</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

// Save Period
function savePeriod(companyName) {
    const fromDate = document.getElementById('edit-from-date').value;
    const toDate = document.getElementById('edit-to-date').value;
    
    companyPeriods[companyName] = { from: fromDate, to: toDate };
    
    // Update display
    const safeId = companyName.replace(/[^a-zA-Z0-9]/g, '_');
    const periodDisplay = document.getElementById(`period-${safeId}`);
    if (periodDisplay) {
        periodDisplay.textContent = `${formatDateDisplay(fromDate)} - ${formatDateDisplay(toDate)}`;
    }
    
    document.querySelector('.modal-overlay').remove();
    showToast('Period updated', 'success');
}

// Sync single company (Task 3 - Full Sync)
async function syncCompany(companyName) {
    const period = companyPeriods[companyName];
    const progressDiv = document.getElementById('sync-progress');
    progressDiv.classList.add('active');
    
    try {
        let endpoint = `/api/sync/full?company=${encodeURIComponent(companyName)}`;
        if (period) {
            endpoint += `&from_date=${period.from}&to_date=${period.to}`;
        }
        
        await apiCall(endpoint, { method: 'POST' });
        showToast(`Full sync started for ${companyName}`, 'success');
        
        // Start polling for status
        syncInterval = setInterval(updateSyncStatus, 1000);
    } catch (error) {
        showToast(`Sync failed: ${error.message}`, 'error');
        progressDiv.classList.remove('active');
    }
}

// Start Sync for selected companies
async function startSync(type) {
    if (selectedCompanies.length === 0) {
        showToast('Please select at least one company', 'warning');
        return;
    }
    
    const progressDiv = document.getElementById('sync-progress');
    progressDiv.classList.add('active');
    
    try {
        for (const company of selectedCompanies) {
            const period = companyPeriods[company];
            let endpoint = `/api/sync/full?company=${encodeURIComponent(company)}`;
            if (period) {
                endpoint += `&from_date=${period.from}&to_date=${period.to}`;
            }
            
            await apiCall(endpoint, { method: 'POST' });
            showToast(`Full sync started for ${company}`, 'success');
        }
        
        // Start polling for status
        syncInterval = setInterval(updateSyncStatus, 1000);
    } catch (error) {
        showToast(`Sync failed: ${error.message}`, 'error');
        progressDiv.classList.remove('active');
    }
}

// Update Sync Status
async function updateSyncStatus() {
    try {
        const status = await apiCall('/api/sync/status');
        
        const progressFill = document.getElementById('progress-fill');
        const progressPercent = document.getElementById('progress-percent');
        const progressTitle = document.getElementById('progress-title');
        const currentTable = document.getElementById('current-table');
        const rowsProcessed = document.getElementById('rows-processed');
        
        progressFill.style.width = `${status.progress}%`;
        progressPercent.textContent = `${status.progress}%`;
        progressTitle.textContent = `Syncing ${status.current_company || ''}`;
        currentTable.textContent = status.current_table || 'Processing...';
        rowsProcessed.textContent = `${status.rows_processed || 0} rows`;
        
        if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(syncInterval);
            
            if (status.status === 'completed') {
                showToast('Sync completed successfully!', 'success');
            } else {
                showToast(`Sync failed: ${status.error_message}`, 'error');
            }
            
            setTimeout(() => {
                document.getElementById('sync-progress').classList.remove('active');
                loadCompanies();
            }, 2000);
        }
    } catch (error) {
        console.error('Status check failed:', error);
    }
}

// Cancel Sync
async function cancelSync() {
    try {
        await apiCall('/api/sync/cancel', { method: 'POST' });
        showToast('Sync cancelled', 'warning');
        clearInterval(syncInterval);
        document.getElementById('sync-progress').classList.remove('active');
    } catch (error) {
        showToast(`Cancel failed: ${error.message}`, 'error');
    }
}

// ==========================================
// TAB 2: SYNC OPTIONS FUNCTIONS
// ==========================================

// Set Sync Interval
function setSyncInterval(minutes) {
    syncIntervalMinutes = minutes;
    showToast(`Sync interval set to ${minutes} minutes`, 'success');
}

// Toggle Auto Sync
function toggleAutoSync() {
    const toggle = document.getElementById('auto-sync-toggle');
    const label = document.getElementById('auto-sync-label');
    const scheduleInfo = document.getElementById('schedule-info');
    
    if (toggle.checked) {
        label.textContent = 'Auto Sync: ON';
        scheduleInfo.style.display = 'flex';
        startAutoSync();
    } else {
        label.textContent = 'Auto Sync: OFF';
        scheduleInfo.style.display = 'none';
        stopAutoSync();
    }
}

// Start Auto Sync Timer
function startAutoSync() {
    if (autoSyncTimer) clearInterval(autoSyncTimer);
    
    updateNextSyncTime();
    
    autoSyncTimer = setInterval(() => {
        runAutoIncrementalSync();
        updateNextSyncTime();
    }, syncIntervalMinutes * 60 * 1000);
    
    showToast(`Auto sync enabled - every ${syncIntervalMinutes} minutes`, 'success');
}

// Stop Auto Sync
function stopAutoSync() {
    if (autoSyncTimer) {
        clearInterval(autoSyncTimer);
        autoSyncTimer = null;
    }
    showToast('Auto sync disabled', 'warning');
}

// Update Next Sync Time Display
function updateNextSyncTime() {
    const nextSyncEl = document.getElementById('next-sync-time');
    if (nextSyncEl) {
        nextSyncEl.textContent = `${syncIntervalMinutes} minutes`;
    }
}

// Run Auto Incremental Sync
async function runAutoIncrementalSync() {
    try {
        const lastSyncEl = document.getElementById('last-sync-time');
        await apiCall('/api/sync/incremental', { method: 'POST' });
        if (lastSyncEl) {
            lastSyncEl.textContent = new Date().toLocaleTimeString();
        }
    } catch (error) {
        console.error('Auto sync failed:', error);
    }
}

// Save Schedule Settings
function saveScheduleSettings() {
    localStorage.setItem('syncIntervalMinutes', syncIntervalMinutes);
    localStorage.setItem('autoSyncEnabled', document.getElementById('auto-sync-toggle').checked);
    showToast('Schedule settings saved', 'success');
}

// ==========================================
// TAB 3: TALLY CONFIGURATION FUNCTIONS
// ==========================================

// Load Tally Config from API
async function loadTallyConfig() {
    try {
        const config = await apiCall('/api/config');
        
        document.getElementById('tally-host').value = config.tally?.server || 'localhost';
        document.getElementById('tally-port').value = config.tally?.port || 9000;
        
        // Check connection status
        checkTallyConnectionStatus();
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

// Check Tally Connection Status
async function checkTallyConnectionStatus() {
    const statusIcon = document.querySelector('#connection-status .status-icon');
    const statusText = document.getElementById('conn-status-text');
    const statusDetail = document.getElementById('conn-status-detail');
    const connectionDetails = document.getElementById('connection-details');
    
    statusIcon.className = 'status-icon checking';
    statusIcon.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    statusText.textContent = 'Checking connection...';
    statusDetail.textContent = 'Please wait';
    
    try {
        const health = await apiCall('/api/health');
        const tallyStatus = health.components?.tally;
        const isConnected = tallyStatus?.status === 'healthy';
        
        if (isConnected) {
            statusIcon.className = 'status-icon connected';
            statusIcon.innerHTML = '<i class="fas fa-check"></i>';
            statusText.textContent = 'Connected';
            statusDetail.textContent = tallyStatus.message || 'Tally is running and accessible';
            connectionDetails.style.display = 'block';
            
            document.getElementById('detail-server').textContent = tallyStatus.server || 'localhost';
            document.getElementById('detail-port').textContent = tallyStatus.port || '9000';
            
            // Get current company from companies API
            try {
                const companies = await apiCall('/api/data/companies');
                document.getElementById('detail-company').textContent = companies.current_company || 'N/A';
            } catch {
                document.getElementById('detail-company').textContent = 'N/A';
            }
        } else {
            statusIcon.className = 'status-icon disconnected';
            statusIcon.innerHTML = '<i class="fas fa-times"></i>';
            statusText.textContent = 'Disconnected';
            statusDetail.textContent = tallyStatus?.message || 'Cannot connect to Tally';
            connectionDetails.style.display = 'none';
        }
    } catch (error) {
        statusIcon.className = 'status-icon disconnected';
        statusIcon.innerHTML = '<i class="fas fa-exclamation-triangle"></i>';
        statusText.textContent = 'Error';
        statusDetail.textContent = error.message;
        connectionDetails.style.display = 'none';
    }
}

// Save Tally Config
async function saveTallyConfig() {
    const host = document.getElementById('tally-host').value;
    const port = document.getElementById('tally-port').value;
    
    if (!host || !port) {
        showToast('Please fill all fields', 'error');
        return;
    }
    
    try {
        await apiCall('/api/config/tally', {
            method: 'POST',
            body: JSON.stringify({ server: host, port: parseInt(port) })
        });
        showToast('Tally configuration saved', 'success');
        checkTallyConnectionStatus();
    } catch (error) {
        showToast(`Save failed: ${error.message}`, 'error');
    }
}

// Test Tally Connection
async function testTallyConnection() {
    const host = document.getElementById('tally-host').value;
    const port = document.getElementById('tally-port').value;
    
    showToast('Testing connection...', 'info');
    
    try {
        const result = await apiCall(`/api/tally/test?server=${host}&port=${port}`);
        
        if (result.connected) {
            showToast('Connection successful!', 'success');
        } else {
            showToast('Connection failed: ' + (result.error || 'Unknown error'), 'error');
        }
        
        checkTallyConnectionStatus();
    } catch (error) {
        showToast(`Connection test failed: ${error.message}`, 'error');
    }
}

// ==========================================
// INITIALIZE
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    loadCompanies();
    
    // Load saved settings
    const savedInterval = localStorage.getItem('syncIntervalMinutes');
    if (savedInterval) {
        syncIntervalMinutes = parseInt(savedInterval);
        const radio = document.querySelector(`input[name="sync-interval"][value="${savedInterval}"]`);
        if (radio) radio.checked = true;
    }
    
    const autoSyncEnabled = localStorage.getItem('autoSyncEnabled') === 'true';
    if (autoSyncEnabled) {
        document.getElementById('auto-sync-toggle').checked = true;
        toggleAutoSync();
    }
});
