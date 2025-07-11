// ===== DUPLICATE MANAGEMENT =====

// ===== DUPLICATE SCANNING =====
async function scanForDuplicates() {
    try {
        updateConnectionStatus('reconnecting', 'Scanning for duplicates...');
        showToast('🔄 Scanning for duplicates...', 'warning');
        
        const response = await makeAuthenticatedRequest(`${API_BASE}/duplicates/scan/`, {
            method: 'POST'
        });
        
        if (response.ok) {
            const result = await response.json();
            updateConnectionStatus('connected', 'Scan complete');
            
            if (result.groups_found > 0) {
                showToast(`🔍 Found ${result.groups_found} duplicate groups with ${result.total_duplicates} transactions`, 'warning');
            } else {
                showToast('✅ No duplicates found!', 'success');
            }
            
            // Reload duplicates list
            loadDuplicates();
        } else {
            const error = await response.json();
            updateConnectionStatus('connected', 'Scan failed');
            showToast(`❌ Duplicate scan failed: ${error.detail}`, 'error');
        }
    } catch (error) {
        updateConnectionStatus('connected', 'Scan failed');
        showToast(`❌ Scan error: ${error.message}`, 'error');
        console.error('Duplicate scan error:', error);
    }
}

// ===== LOAD DUPLICATES =====
async function loadDuplicates() {
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/duplicates/?limit=50`);
        
        if (response.ok) {
            const data = await response.json();
            renderDuplicates(data.duplicate_groups || []);
            updateDuplicateStats(data);
        } else {
            showToast('❌ Failed to load duplicates', 'error');
        }
    } catch (error) {
        showToast(`❌ Error loading duplicates: ${error.message}`, 'error');
        console.error('Load duplicates error:', error);
    }
}

// ===== RENDER DUPLICATES =====
function renderDuplicates(groups) {
    const container = document.getElementById('duplicates-list');
    if (!container) return;
    
    if (!groups || groups.length === 0) {
        container.innerHTML = `
            <div class="text-center p-md">
                <div style="font-size: 2rem; margin-bottom: var(--space-md);">🎉</div>
                <h3>No Duplicates Found</h3>
                <p style="color: var(--color-text-secondary);">Your transactions are clean!</p>
                <button class="btn btn-primary" onclick="scanForDuplicates()" style="margin-top: var(--space-md);">
                    🔄 Scan Again
                </button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = groups.map(group => `
        <div class="card duplicate-group" style="border-left: 4px solid var(--color-warning);">
            <div class="duplicate-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-md);">
                <div>
                    <h4>🔍 Duplicate Group #${group.id}</h4>
                    <div style="font-size: var(--font-size-sm); color: var(--color-text-secondary);">
                        ${group.transaction_count} transactions • ${Math.round(group.similarity_score * 100)}% similarity
                    </div>
                </div>
                <div style="display: flex; gap: var(--space-sm);">
                    <button class="btn btn-sm btn-secondary" onclick="viewDuplicateDetails(${group.id})">
                        👁️ Details
                    </button>
                    <button class="btn btn-sm btn-success" onclick="resolveDuplicate(${group.id}, 'keep_first')">
                        ✅ Keep First
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="resolveDuplicate(${group.id}, 'delete_all')">
                        🗑️ Delete All
                    </button>
                </div>
            </div>
            
            <div class="duplicate-transactions">
                ${group.transactions.map((txn, index) => `
                    <div class="duplicate-transaction" style="
                        display: grid; 
                        grid-template-columns: auto auto 1fr auto; 
                        gap: var(--space-md); 
                        align-items: center; 
                        padding: var(--space-sm);
                        background: ${index === 0 ? 'var(--color-success)' : 'var(--color-bg)'};
                        border-radius: var(--radius-sm);
                        margin-bottom: var(--space-xs);
                        opacity: ${index === 0 ? '1' : '0.8'};
                    ">
                        <div style="font-weight: var(--font-weight-bold); color: ${index === 0 ? 'white' : 'var(--color-text)'};">
                            ${index === 0 ? '👑' : '📄'} #${index + 1}
                        </div>
                        <div style="font-weight: var(--font-weight-semibold); color: ${index === 0 ? 'white' : 'var(--color-text)'};">
                            ${formatDate(txn.date)}
                        </div>
                        <div style="color: ${index === 0 ? 'white' : 'var(--color-text)'};">
                            <div style="font-weight: var(--font-weight-medium);">${txn.beneficiary}</div>
                            ${txn.category ? `<div style="font-size: var(--font-size-sm); opacity: 0.8;">🏷️ ${txn.category}</div>` : ''}
                        </div>
                        <div style="font-weight: var(--font-weight-bold); color: ${index === 0 ? 'white' : (txn.amount < 0 ? 'var(--color-danger)' : 'var(--color-success)')};">
                            ${formatAmount(txn.amount)}
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

// ===== DUPLICATE RESOLUTION =====
async function resolveDuplicate(groupId, action) {
    let confirmMessage = '';
    
    switch (action) {
        case 'keep_first':
            confirmMessage = 'Keep the first transaction and delete the rest?';
            break;
        case 'delete_all':
            confirmMessage = 'Delete ALL transactions in this group? This cannot be undone!';
            break;
        case 'keep_original':
            confirmMessage = 'Keep the original transaction and delete duplicates?';
            break;
        default:
            return;
    }
    
    if (!confirm(confirmMessage)) {
        return;
    }
    
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/duplicates/${groupId}/resolve`, {
            method: 'POST',
            body: JSON.stringify({
                action: action,
                resolution_notes: `Resolved via UI action: ${action}`
            })
        });
        
        if (response.ok) {
            const result = await response.json();
            showToast(`✅ ${result.message}`, 'success');
            
            // Reload duplicates list
            loadDuplicates();
            
            // Refresh transactions if needed
            if (window.transactionManager) {
                resetTransactionsPagination();
                loadTransactionsPaginated();
            }
        } else {
            const error = await response.json();
            showToast(`❌ Resolution failed: ${error.detail}`, 'error');
        }
    } catch (error) {
        showToast(`❌ Resolution error: ${error.message}`, 'error');
        console.error('Duplicate resolution error:', error);
    }
}

// ===== DUPLICATE DETAILS =====
async function viewDuplicateDetails(groupId) {
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/duplicates/${groupId}`);
        
        if (response.ok) {
            const group = await response.json();
            showDuplicateModal(group);
        } else {
            showToast('❌ Failed to load duplicate details', 'error');
        }
    } catch (error) {
        showToast(`❌ Error loading details: ${error.message}`, 'error');
        console.error('Duplicate details error:', error);
    }
}

function showDuplicateModal(group) {
    // Create modal content
    const modalContent = `
        <div class="modal-overlay" onclick="closeDuplicateModal()">
            <div class="modal-content" onclick="event.stopPropagation();" style="max-width: 800px;">
                <div class="modal-header">
                    <h3>🔍 Duplicate Group #${group.id} Details</h3>
                    <button class="modal-close" onclick="closeDuplicateModal()">×</button>
                </div>
                <div class="modal-body">
                    <div class="duplicate-info" style="margin-bottom: var(--space-lg);">
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--space-md);">
                            <div class="info-card">
                                <div class="info-label">Similarity Score</div>
                                <div class="info-value">${Math.round(group.similarity_score * 100)}%</div>
                            </div>
                            <div class="info-card">
                                <div class="info-label">Detection Method</div>
                                <div class="info-value">${group.detection_method}</div>
                            </div>
                            <div class="info-card">
                                <div class="info-label">Transactions</div>
                                <div class="info-value">${group.transaction_count}</div>
                            </div>
                            <div class="info-card">
                                <div class="info-label">Status</div>
                                <div class="info-value">${group.status}</div>
                            </div>
                        </div>
                    </div>
                    
                    <h4>Transactions in Group:</h4>
                    <div class="duplicate-details">
                        ${group.transactions.map((txn, index) => `
                            <div class="transaction-detail-card" style="margin-bottom: var(--space-md); padding: var(--space-md); border: 1px solid var(--color-border); border-radius: var(--radius-md);">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-sm);">
                                    <h5>${index === 0 ? '👑 Primary' : '📄 Duplicate'} Transaction #${txn.id}</h5>
                                    <button class="btn btn-sm btn-danger" onclick="deleteSpecificTransaction(${txn.id})">🗑️ Delete This One</button>
                                </div>
                                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-sm);">
                                    <div><strong>Date:</strong> ${formatDate(txn.date)}</div>
                                    <div><strong>Amount:</strong> ${formatAmount(txn.amount)}</div>
                                    <div><strong>Beneficiary:</strong> ${txn.beneficiary}</div>
                                    <div><strong>Category:</strong> ${txn.category || 'None'}</div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="closeDuplicateModal()">Close</button>
                    <button class="btn btn-success" onclick="resolveDuplicate(${group.id}, 'keep_first'); closeDuplicateModal();">✅ Keep First</button>
                    <button class="btn btn-danger" onclick="resolveDuplicate(${group.id}, 'delete_all'); closeDuplicateModal();">🗑️ Delete All</button>
                </div>
            </div>
        </div>
    `;
    
    // Add modal to page
    const modalContainer = document.createElement('div');
    modalContainer.id = 'duplicate-modal';
    modalContainer.innerHTML = modalContent;
    document.body.appendChild(modalContainer);
}

function closeDuplicateModal() {
    const modal = document.getElementById('duplicate-modal');
    if (modal) {
        modal.remove();
    }
}

// ===== DELETE SPECIFIC TRANSACTION =====
async function deleteSpecificTransaction(transactionId) {
    if (!confirm('Delete this specific transaction?')) {
        return;
    }
    
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/transactions/${transactionId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('🗑️ Transaction deleted', 'success');
            closeDuplicateModal();
            loadDuplicates();
        } else {
            showToast('❌ Failed to delete transaction', 'error');
        }
    } catch (error) {
        showToast(`❌ Delete error: ${error.message}`, 'error');
        console.error('Delete specific transaction error:', error);
    }
}

// ===== DUPLICATE STATISTICS =====
function updateDuplicateStats(data) {
    // This would update duplicate statistics if we have a stats container
    console.log('Duplicate stats:', data);
}

// ===== DUPLICATE SETTINGS =====
function configureDuplicateSettings() {
    showToast('⚙️ Duplicate settings coming soon', 'warning');
}

// ===== DUPLICATE MANAGER OBJECT =====
window.duplicateManager = {
    init() {
        console.log('Initializing duplicate manager');
        loadDuplicates();
    },
    
    scan() {
        scanForDuplicates();
    },
    
    configure() {
        configureDuplicateSettings();
    }
};

// Make functions globally available
window.scanForDuplicates = scanForDuplicates;
window.configureDuplicateSettings = configureDuplicateSettings;
window.resolveDuplicate = resolveDuplicate;
window.viewDuplicateDetails = viewDuplicateDetails;