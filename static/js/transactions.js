// ===== TRANSACTION MANAGEMENT =====

// ===== STAGED TRANSACTION ACTIONS =====
async function approveStaged(id) {
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/upload/staged/${id}/approve`, {
            method: 'POST'
        });
        
        if (response.ok) {
            showToast('✅ Transaction approved', 'success');
            resetStagedPagination();
            loadStagedTransactionsPaginated();
        } else {
            const error = await response.json();
            showToast(`❌ Failed to approve: ${error.detail}`, 'error');
        }
    } catch (error) {
        showToast(`❌ Error approving transaction: ${error.message}`, 'error');
        console.error('Approve staged error:', error);
    }
}

async function editStaged(id) {
    // TODO: Implement edit modal
    showToast('✏️ Edit functionality coming soon', 'warning');
}

async function deleteStaged(id) {
    if (!confirm('Are you sure you want to delete this staged transaction?')) {
        return;
    }
    
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/upload/staged/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('🗑️ Staged transaction deleted', 'success');
            resetStagedPagination();
            loadStagedTransactionsPaginated();
        } else {
            const error = await response.json();
            showToast(`❌ Failed to delete: ${error.detail}`, 'error');
        }
    } catch (error) {
        showToast(`❌ Error deleting transaction: ${error.message}`, 'error');
        console.error('Delete staged error:', error);
    }
}

async function approveAllStaged() {
    if (!confirm('Are you sure you want to approve ALL staged transactions?')) {
        return;
    }
    
    try {
        // Get all staged transaction IDs
        const pagination = window.stagedPagination;
        if (!pagination || !pagination.items.length) {
            showToast('❌ No staged transactions to approve', 'warning');
            return;
        }
        
        const stagedIds = pagination.items.map(item => item.id);
        
        const response = await makeAuthenticatedRequest(`${API_BASE}/upload/staged/bulk-approve`, {
            method: 'POST',
            body: JSON.stringify({
                staged_ids: stagedIds,
                auto_approve_high_confidence: true,
                confidence_threshold: 0.8
            })
        });
        
        if (response.ok) {
            const result = await response.json();
            showToast(`✅ Approved ${result.approved_count} transactions`, 'success');
            resetStagedPagination();
            loadStagedTransactionsPaginated();
        } else {
            const error = await response.json();
            showToast(`❌ Bulk approve failed: ${error.detail}`, 'error');
        }
    } catch (error) {
        showToast(`❌ Error approving all: ${error.message}`, 'error');
        console.error('Approve all error:', error);
    }
}

async function deleteAllStaged() {
    if (!confirm('⚠️ Are you sure you want to DELETE ALL staged transactions? This cannot be undone!')) {
        return;
    }
    
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/upload/staged/bulk-delete`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            const result = await response.json();
            showToast(`🗑️ Deleted ${result.deleted_count} staged transactions`, 'success');
            resetStagedPagination();
            loadStagedTransactionsPaginated();
        } else {
            const error = await response.json();
            showToast(`❌ Bulk delete failed: ${error.detail}`, 'error');
        }
    } catch (error) {
        showToast(`❌ Error deleting all: ${error.message}`, 'error');
        console.error('Delete all error:', error);
    }
}

// ===== CONFIRMED TRANSACTION ACTIONS =====
async function editTransaction(id) {
    // TODO: Implement edit modal
    showToast('✏️ Edit functionality coming soon', 'warning');
}

async function deleteTransaction(id) {
    if (!confirm('Are you sure you want to delete this transaction?')) {
        return;
    }
    
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/transactions/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('🗑️ Transaction deleted', 'success');
            resetTransactionsPagination();
            loadTransactionsPaginated();
        } else {
            const error = await response.json();
            showToast(`❌ Failed to delete: ${error.detail}`, 'error');
        }
    } catch (error) {
        showToast(`❌ Error deleting transaction: ${error.message}`, 'error');
        console.error('Delete transaction error:', error);
    }
}

// ===== SEARCH FUNCTIONALITY =====
let searchTimeout = null;

function setupTransactionSearch() {
    const searchInput = document.getElementById('search-transactions');
    if (!searchInput) return;
    
    searchInput.addEventListener('input', function(e) {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            searchTransactions(e.target.value);
        }, 500); // Debounce search
    });
}

async function searchTransactions(query) {
    if (!query.trim()) {
        // If empty search, reload normal transactions
        resetTransactionsPagination();
        loadTransactionsPaginated();
        return;
    }
    
    try {
        const response = await makeAuthenticatedRequest(
            `${API_BASE}/transactions/search/?q=${encodeURIComponent(query)}&limit=${ITEMS_PER_PAGE}`
        );
        
        if (response.ok) {
            const data = await response.json();
            // Reset pagination and show search results
            resetTransactionsPagination();
            renderTransactions(data.transactions || data.results || []);
            updatePaginationInfo('transactions', data.transactions?.length || 0, data.total || 0);
        } else {
            showToast('❌ Search failed', 'error');
        }
    } catch (error) {
        showToast(`❌ Search error: ${error.message}`, 'error');
        console.error('Search error:', error);
    }
}

// ===== EXPORT FUNCTIONALITY =====
async function exportTransactions() {
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/transactions/export/?format=csv`);
        
        if (response.ok) {
            const data = await response.json();
            
            // Convert to CSV and download
            const csvContent = convertToCSV(data.data);
            downloadCSV(csvContent, `transactions_${new Date().toISOString().split('T')[0]}.csv`);
            
            showToast('📥 Export completed', 'success');
        } else {
            showToast('❌ Export failed', 'error');
        }
    } catch (error) {
        showToast(`❌ Export error: ${error.message}`, 'error');
        console.error('Export error:', error);
    }
}

function convertToCSV(data) {
    if (!data || !data.length) return '';
    
    const headers = Object.keys(data[0]);
    const csvHeaders = headers.join(',');
    
    const csvRows = data.map(row => 
        headers.map(header => {
            const value = row[header];
            // Escape commas and quotes
            if (typeof value === 'string' && (value.includes(',') || value.includes('"'))) {
                return `"${value.replace(/"/g, '""')}"`;
            }
            return value;
        }).join(',')
    );
    
    return [csvHeaders, ...csvRows].join('\n');
}

function downloadCSV(csvContent, filename) {
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    
    if (link.download !== undefined) {
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
}

// ===== TRANSACTION MANAGER OBJECT =====
window.transactionManager = {
    init() {
        console.log('Initializing transaction manager');
        resetTransactionsPagination();
        loadTransactionsPaginated();
        setupTransactionSearch();
    },
    
    loadMore() {
        loadTransactionsPaginated(true);
    },
    
    export() {
        exportTransactions();
    }
};

// ===== STAGED TRANSACTIONS MANAGER =====
window.stagedTransactions = {
    init() {
        console.log('Initializing staged transactions');
        resetStagedPagination();
        loadStagedTransactionsPaginated();
    },
    
    loadMore() {
        loadStagedTransactionsPaginated(true);
    },
    
    approveAll() {
        approveAllStaged();
    },
    
    deleteAll() {
        deleteAllStaged();
    }
};

// Make functions globally available
window.approveStaged = approveStaged;
window.editStaged = editStaged;
window.deleteStaged = deleteStaged;
window.approveAllStaged = approveAllStaged;
window.deleteAllStaged = deleteAllStaged;
window.editTransaction = editTransaction;
window.deleteTransaction = deleteTransaction;
window.exportTransactions = exportTransactions;