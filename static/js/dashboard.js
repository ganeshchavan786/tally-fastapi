// Dashboard Page JavaScript

let currentCompany = '';

// Load Dashboard Data
async function loadDashboard() {
    await Promise.all([
        loadStats(),
        loadCompanyFilter(),
        loadTableStats()
    ]);
}

// Load Stats
async function loadStats() {
    try {
        const stats = await apiCall('/api/data/stats');
        
        let totalRecords = 0;
        let companies = new Set();
        
        Object.entries(stats).forEach(([key, value]) => {
            if (typeof value === 'number') {
                totalRecords += value;
            }
        });
        
        document.getElementById('total-records').textContent = formatNumber(totalRecords);
        
        // Get companies count
        const companyData = await apiCall('/api/data/companies').catch(() => ({ count: 0 }));
        document.getElementById('total-companies').textContent = companyData.count || 0;
        
        // Get last sync
        const syncStatus = await apiCall('/api/sync/status').catch(() => ({}));
        if (syncStatus.completed_at) {
            document.getElementById('last-sync').textContent = formatTime(syncStatus.completed_at);
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

// Load Company Filter
async function loadCompanyFilter() {
    try {
        const data = await apiCall('/api/data/companies');
        const select = document.getElementById('company-filter');
        
        if (data.companies) {
            data.companies.forEach(company => {
                const option = document.createElement('option');
                option.value = company.name;
                option.textContent = company.name;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Failed to load companies:', error);
    }
}

// Filter by Company
function filterByCompany() {
    currentCompany = document.getElementById('company-filter').value;
    loadTableStats();
}

// Load Table Stats
async function loadTableStats() {
    try {
        let endpoint = '/api/data/stats';
        if (currentCompany) {
            endpoint += `?company=${encodeURIComponent(currentCompany)}`;
        }
        
        const stats = await apiCall(endpoint);
        
        const masterTables = ['mst_group', 'mst_ledger', 'mst_stock_group', 'mst_stock_item', 
            'mst_stock_category', 'mst_godown', 'mst_uom', 'mst_vouchertype', 
            'mst_cost_category', 'mst_cost_centre', 'mst_currency', 'mst_employee'];
        
        const transactionTables = ['trn_voucher', 'trn_accounting', 'trn_inventory', 
            'trn_cost_centre', 'trn_bill', 'trn_batch'];
        
        renderTableGrid('master-tables', masterTables, stats);
        renderTableGrid('transaction-tables', transactionTables, stats);
    } catch (error) {
        console.error('Failed to load table stats:', error);
    }
}

// Render Table Grid
function renderTableGrid(containerId, tables, stats) {
    const container = document.getElementById(containerId);
    
    container.innerHTML = tables.map(table => {
        const count = stats[table] || 0;
        const displayName = table.replace('mst_', '').replace('trn_', '').replace(/_/g, ' ');
        return `
            <div class="table-item">
                <span class="table-name">${displayName}</span>
                <span class="table-count ${count === 0 ? 'zero' : ''}">${formatNumber(count)}</span>
            </div>
        `;
    }).join('');
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
});
