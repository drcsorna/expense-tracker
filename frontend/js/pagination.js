// ===== PAGINATION MANAGER - FIXES THE .map() ERROR =====

// Configuration
const ITEMS_PER_PAGE = 25; // 2025 best practice: smaller initial loads

// Pagination state management
class PaginationManager {
    constructor(type) {
        this.type = type; // 'staged' or 'transactions'
        this.reset();
    }
    
    reset() {
        this.offset = 0;
        this.total = 0;
        this.hasMore = false;
        this.loading = false;
        this.items = [];
    }
    
    // THE FIX: Properly extract arrays from paginated API responses
    updateFromApiResponse(apiResponse) {
        // API returns: { total: X, offset: Y, limit: Z, staged_transactions: [...] }
        // We need to extract the actual array
        
        let newItems = [];
        
        if (this.type === 'staged') {
            newItems = apiResponse.staged_transactions || [];
        } else if (this.type === 'transactions') {
            newItems = apiResponse.transactions || [];
        }
        
        // Update pagination state
        this.total = apiResponse.total || 0;
        this.hasMore = this.offset + ITEMS_PER_PAGE < this.total;
        
        return newItems;
    }
    
    appendItems(newItems) {
        this.items = [...this.items, ...newItems];
        this.offset += ITEMS_PER_PAGE;
    }
    
    replaceItems(newItems) {
        this.items = newItems;
        this.offset = ITEMS_PER_PAGE;
    }
}

// ===== ENHANCED API FUNCTIONS WITH PAGINATION =====
async function loadStagedTransactionsPaginated(loadMore = false) {
    if (!window.stagedPagination) {
        window.stagedPagination = new PaginationManager('staged');
    }
    
    const pagination = window.stagedPagination;
    
    if (pagination.loading) return;
    
    pagination.loading = true;
    updateLoadMoreButton('staged', true);
    
    try {
        const offset = loadMore ? pagination.offset : 0;
        
        console.log(`Loading staged transactions: offset=${offset}, limit=${ITEMS_PER_PAGE}, loadMore=${loadMore}`);
        
        const response = await fetch(`${API_BASE}/upload/staged/?limit=${ITEMS_PER_PAGE}&offset=${offset}`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const apiResponse = await response.json();
        console.log('API Response:', apiResponse);
        
        // THE FIX: Extract array from API response
        const newItems = pagination.updateFromApiResponse(apiResponse);
        
        if (loadMore) {
            pagination.appendItems(newItems);
        } else {
            pagination.reset();
            pagination.replaceItems(newItems);
        }
        
        // Render the items
        renderStagedTransactions(pagination.items);
        updatePaginationInfo('staged', pagination.items.length, pagination.total);
        updateLoadMoreButton('staged', false);
        
        console.log(`Loaded ${newItems.length} staged transactions, total: ${pagination.items.length}`);
        
    } catch (error) {
        console.error('Failed to load staged transactions:', error);
        showToast(`❌ Failed to load staged transactions: ${error.message}`, 'error');
    } finally {
        pagination.loading = false;
    }
}

async function loadTransactionsPaginated(loadMore = false) {
    if (!window.transactionsPagination) {
        window.transactionsPagination = new PaginationManager('transactions');
    }
    
    const pagination = window.transactionsPagination;
    
    if (pagination.loading) return;
    
    pagination.loading = true;
    updateLoadMoreButton('transactions', true);
    
    try {
        const offset = loadMore ? pagination.offset : 0;
        
        console.log(`Loading transactions: offset=${offset}, limit=${ITEMS_PER_PAGE}, loadMore=${loadMore}`);
        
        const response = await fetch(`${API_BASE}/transactions/?limit=${ITEMS_PER_PAGE}&offset=${offset}`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const apiResponse = await response.json();
        console.log('API Response:', apiResponse);
        
        // THE FIX: Extract array from API response
        const newItems = pagination.updateFromApiResponse(apiResponse);
        
        if (loadMore) {
            pagination.appendItems(newItems);
        } else {
            pagination.reset();
            pagination.replaceItems(newItems);
        }
        
        // Render the items
        renderTransactions(pagination.items);
        updatePaginationInfo('transactions', pagination.items.length, pagination.total);
        updateLoadMoreButton('transactions', false);
        
        console.log(`Loaded ${newItems.length} transactions, total: ${pagination.items.length}`);
        
    } catch (error) {
        console.error('Failed to load transactions:', error);
        showToast(`❌ Failed to load transactions: ${error.message}`, 'error');
    } finally {
        pagination.loading = false;
    }
}

// ===== PAGINATION UI FUNCTIONS =====
function updatePaginationInfo(type, showing, total) {
    const infoElement = document.getElementById(`${type}-pagination-info`);
    if (!infoElement) return;
    
    if (total === 0) {
        infoElement.textContent = `No ${type} found`;
        infoElement.style.display = 'none';
    } else {
        infoElement.textContent = `Showing ${showing} of ${total} ${type}`;
        infoElement.style.display = 'block';
    }
}

function updateLoadMoreButton(type, loading) {
    const container = document.getElementById(`${type}-load-more`);
    if (!container) return;
    
    const button = container.querySelector('.btn-load-more');
    const text = container.querySelector('.load-more-text');
    
    const pagination = type === 'staged' ? window.stagedPagination : window.transactionsPagination;
    
    if (pagination && pagination.hasMore) {
        container.classList.remove('hidden');
        button.disabled = loading;
        
        if (loading) {
            text.innerHTML = '<span class="loading-spinner"></span>Loading...';
        } else {
            text.textContent = `Load More ${type === 'staged' ? 'Transactions' : 'Transactions'}`;
        }
    } else {
        container.classList.add('hidden');
    }
}

// ===== LOAD MORE HANDLERS =====
function loadMoreStaged() {
    loadStagedTransactionsPaginated(true);
}

function loadMoreTransactions() {
    loadTransactionsPaginated(true);
}

// ===== RENDER FUNCTIONS =====
function renderStagedTransactions(items) {
    const container = document.getElementById('staged-list');
    if (!container) {
        console.warn('staged-list container not found');
        return;
    }
    
    if (!Array.isArray(items) || items.length === 0) {
        container.innerHTML = `
            <div class="text-center p-md">
                <span style="color: var(--color-text-secondary);">No transactions pending review</span>
            </div>
        `;
        return;
    }
    
    container.innerHTML = items.map(transaction => `
        <div class="card" style="border-left: 4px solid ${transaction.suggested_category ? 'var(--color-primary)' : 'var(--color-warning)'};">
            <div style="display: grid; grid-template-columns: auto 1fr auto auto; gap: var(--space-md); align-items: center;">
                <div style="font-weight: var(--font-weight-semibold);">
                    ${formatDate(transaction.transaction_date)}
                </div>
                <div>
                    <div style="font-weight: var(--font-weight-medium);">${transaction.beneficiary}</div>
                    ${transaction.suggested_category ? 
                        `<div style="font-size: var(--font-size-sm); color: var(--color-primary);">
                            💡 Suggested: ${transaction.suggested_category} (${Math.round((transaction.confidence || 0) * 100)}% confidence)
                        </div>` : ''}
                </div>
                <div style="font-weight: var(--font-weight-bold); color: ${transaction.amount < 0 ? 'var(--color-danger)' : 'var(--color-success)'};">
                    ${formatAmount(transaction.amount)}
                </div>
                <div style="display: flex; gap: var(--space-sm);">
                    <button class="btn btn-success btn-sm" onclick="approveStaged(${transaction.id})">✅</button>
                    <button class="btn btn-secondary btn-sm" onclick="editStaged(${transaction.id})">✏️</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteStaged(${transaction.id})">🗑️</button>
                </div>
            </div>
        </div>
    `).join('');
}

function renderTransactions(items) {
    const container = document.getElementById('transactions-list');
    if (!container) {
        console.warn('transactions-list container not found');
        return;
    }
    
    if (!Array.isArray(items) || items.length === 0) {
        container.innerHTML = `
            <div class="text-center p-md">
                <span style="color: var(--color-text-secondary);">No transactions found</span>
            </div>
        `;
        return;
    }
    
    container.innerHTML = items.map(transaction => `
        <div class="card">
            <div style="display: grid; grid-template-columns: auto 1fr auto auto auto; gap: var(--space-md); align-items: center;">
                <div style="font-weight: var(--font-weight-semibold);">
                    ${formatDate(transaction.transaction_date)}
                </div>
                <div>
                    <div style="font-weight: var(--font-weight-medium);">${transaction.beneficiary}</div>
                    ${transaction.category ? 
                        `<div style="font-size: var(--font-size-sm); color: var(--color-text-secondary);">
                            🏷️ ${transaction.category}
                        </div>` : ''}
                </div>
                <div style="font-weight: var(--font-weight-bold); color: ${transaction.amount < 0 ? 'var(--color-danger)' : 'var(--color-success)'};">
                    ${formatAmount(transaction.amount)}
                </div>
                <div style="font-size: var(--font-size-sm); color: var(--color-text-secondary);">
                    ${transaction.categorization_method || 'manual'}
                </div>
                <div style="display: flex; gap: var(--space-sm);">
                    <button class="btn btn-secondary btn-sm" onclick="editTransaction(${transaction.id})">✏️</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteTransaction(${transaction.id})">🗑️</button>
                </div>
            </div>
        </div>
    `).join('');
}

// ===== RESET FUNCTIONS =====
function resetStagedPagination() {
    if (window.stagedPagination) {
        window.stagedPagination.reset();
    }
}

function resetTransactionsPagination() {
    if (window.transactionsPagination) {
        window.transactionsPagination.reset();
    }
}

// Make functions globally available
window.loadStagedTransactionsPaginated = loadStagedTransactionsPaginated;
window.loadTransactionsPaginated = loadTransactionsPaginated;
window.loadMoreStaged = loadMoreStaged;
window.loadMoreTransactions = loadMoreTransactions;
window.renderStagedTransactions = renderStagedTransactions;
window.renderTransactions = renderTransactions;
window.resetStagedPagination = resetStagedPagination;
window.resetTransactionsPagination = resetTransactionsPagination;