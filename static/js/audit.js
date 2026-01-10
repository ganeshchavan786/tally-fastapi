// Audit Page JavaScript

// Load Audit Stats
async function loadAuditStats() {
    try {
        const stats = await apiCall('/api/audit/stats');
        
        document.getElementById('insert-count').textContent = formatNumber(stats.by_action?.INSERT || 0);
        document.getElementById('update-count').textContent = formatNumber(stats.by_action?.UPDATE || 0);
        document.getElementById('delete-count').textContent = formatNumber(stats.by_action?.DELETE || 0);
        document.getElementById('pending-restore').textContent = formatNumber(stats.pending_deleted_records || 0);
    } catch (error) {
        console.error('Failed to load audit stats:', error);
    }
}

// Load Audit History
async function loadAuditHistory() {
    const list = document.getElementById('audit-list');
    list.innerHTML = '<div class="loading"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';
    
    try {
        const action = document.getElementById('action-filter').value;
        let endpoint = '/api/audit/history?limit=50';
        if (action) endpoint += `&action=${action}`;
        
        const data = await apiCall(endpoint);
        
        if (!data.records || data.records.length === 0) {
            list.innerHTML = '<div class="empty-state"><i class="fas fa-history"></i><p>No audit records found</p></div>';
            return;
        }
        
        list.innerHTML = data.records.map(record => {
            const iconClass = record.action.toLowerCase();
            const icon = record.action === 'INSERT' ? 'plus' : record.action === 'UPDATE' ? 'edit' : 'trash';
            
            return `
                <div class="audit-item">
                    <div class="audit-icon ${iconClass}"><i class="fas fa-${icon}"></i></div>
                    <div class="audit-content">
                        <div class="audit-header">
                            <span class="audit-title">${record.record_name || record.record_guid}</span>
                            <span class="audit-time">${formatDate(record.created_at)} ${formatTime(record.created_at)}</span>
                        </div>
                        <div class="audit-meta">
                            <span class="audit-badge table">${record.table_name}</span>
                            <span class="audit-badge company">${record.company}</span>
                        </div>
                    </div>
                    ${record.action === 'DELETE' ? `
                        <div class="audit-actions">
                            <button class="btn btn-restore" onclick="restoreRecord(${record.id})">
                                <i class="fas fa-undo"></i> Restore
                            </button>
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
    } catch (error) {
        list.innerHTML = `<div class="empty-state"><i class="fas fa-exclamation-triangle"></i><p>Error: ${error.message}</p></div>`;
    }
}

// Restore Record
async function restoreRecord(id) {
    if (!confirm('Are you sure you want to restore this record?')) return;
    
    try {
        await apiCall(`/api/audit/restore/${id}`, { method: 'POST' });
        showToast('Record restored successfully', 'success');
        loadAuditStats();
        loadAuditHistory();
    } catch (error) {
        showToast(`Restore failed: ${error.message}`, 'error');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadAuditStats();
    loadAuditHistory();
});
