// ===== FILE UPLOAD MANAGEMENT =====

let currentUploadSession = null;

// ===== TRANSACTION FILE UPLOAD =====
async function uploadTransactionFile() {
    const fileInput = document.getElementById('transaction-file');
    const file = fileInput.files[0];
    
    if (!file) {
        showToast('❌ Please select a file', 'error');
        return;
    }

    // Validate file type
    const allowedTypes = ['.csv', '.xlsx', '.xls'];
    const fileExtension = '.' + file.name.split('.').pop().toLowerCase();
    
    if (!allowedTypes.includes(fileExtension)) {
        showToast('❌ Please select a CSV or Excel file', 'error');
        return;
    }
    
    // Validate file size (50MB limit)
    const maxSize = 50 * 1024 * 1024; // 50MB
    if (file.size > maxSize) {
        showToast('❌ File too large. Maximum size is 50MB', 'error');
        return;
    }

    try {
        showUploadProgress();
        updateConnectionStatus('reconnecting', 'Uploading file...');
        
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`${API_BASE}/upload/transactions/`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${authToken}` },
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }
        
        const result = await response.json();
        currentUploadSession = result.session_id;
        
        showToast(`🚀 ${file.name} upload started!`, 'success');
        updateConnectionStatus('connected', 'Processing file...');
        
        // Start monitoring upload progress
        monitorUploadProgress(currentUploadSession);
        
        // Clear the file input
        fileInput.value = '';
        
    } catch (error) {
        hideUploadProgress();
        updateConnectionStatus('disconnected', 'Upload failed');
        showToast(`❌ Upload failed: ${error.message}`, 'error');
        console.error('Upload error:', error);
    }
}

// ===== BOOTSTRAP FILE UPLOAD =====
async function uploadBootstrapFile() {
    const fileInput = document.getElementById('bootstrap-file');
    const file = fileInput.files[0];
    
    if (!file) {
        showToast('❌ Please select a bootstrap file', 'error');
        return;
    }

    try {
        showUploadProgress();
        updateConnectionStatus('reconnecting', 'Uploading bootstrap file...');
        
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`${API_BASE}/categorization/bootstrap/`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${authToken}` },
            body: formData
        });
        
        const result = await response.json();
        
        if (response.ok) {
            hideUploadProgress();
            updateConnectionStatus('connected', 'Bootstrap complete');
            showToast(`✅ Bootstrap complete! Learned ${result.rules_created} categorization rules`, 'success');
            
            // Reload categories if we have a category manager
            if (window.categoryManager && window.categoryManager.loadCategories) {
                window.categoryManager.loadCategories();
            }
        } else {
            hideUploadProgress();
            updateConnectionStatus('disconnected', 'Bootstrap failed');
            showToast(`❌ Bootstrap failed: ${result.detail}`, 'error');
        }
        
        // Clear the file input
        fileInput.value = '';
        
    } catch (error) {
        hideUploadProgress();
        updateConnectionStatus('disconnected', 'Bootstrap failed');
        showToast(`❌ Bootstrap failed: ${error.message}`, 'error');
        console.error('Bootstrap error:', error);
    }
}

// ===== UPLOAD PROGRESS MONITORING =====
async function monitorUploadProgress(sessionId) {
    if (!sessionId) return;
    
    const maxAttempts = 120; // 2 minutes max
    let attempts = 0;
    
    const checkProgress = async () => {
        try {
            const response = await makeAuthenticatedRequest(`${API_BASE}/upload/progress/${sessionId}`);
            
            if (response.ok) {
                const progress = await response.json();
                updateUploadProgressUI(progress);
                
                if (progress.stage === 'completed') {
                    hideUploadProgress();
                    updateConnectionStatus('connected', 'Upload complete');
                    showToast(`✅ Upload completed! ${progress.staged_count} transactions staged for review`, 'success');
                    
                    // Refresh staged transactions
                    if (window.stagedTransactions) {
                        resetStagedPagination();
                        loadStagedTransactionsPaginated();
                    }
                    
                    return; // Stop monitoring
                } else if (progress.stage === 'failed') {
                    hideUploadProgress();
                    updateConnectionStatus('disconnected', 'Upload failed');
                    showToast(`❌ Upload failed: ${progress.error || 'Unknown error'}`, 'error');
                    return; // Stop monitoring
                }
                
                // Continue monitoring if still processing
                if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(checkProgress, 1000); // Check every second
                } else {
                    hideUploadProgress();
                    updateConnectionStatus('disconnected', 'Upload timeout');
                    showToast('❌ Upload monitoring timed out', 'error');
                }
            } else {
                console.warn('Progress check failed:', response.status);
                if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(checkProgress, 2000); // Retry with longer delay
                }
            }
        } catch (error) {
            console.error('Progress monitoring error:', error);
            if (attempts < maxAttempts) {
                attempts++;
                setTimeout(checkProgress, 2000); // Retry
            }
        }
    };
    
    checkProgress();
}

// ===== UPLOAD PROGRESS UI =====
function showUploadProgress() {
    const container = document.getElementById('upload-results');
    if (!container) return;
    
    container.innerHTML = `
        <div class="upload-progress">
            <h4>📤 Upload Progress</h4>
            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
                </div>
                <div class="progress-text" id="progress-text">Initializing...</div>
            </div>
            <div class="progress-details" id="progress-details"></div>
        </div>
    `;
    
    container.classList.remove('hidden');
}

function updateUploadProgressUI(progress) {
    const fillElement = document.getElementById('progress-fill');
    const textElement = document.getElementById('progress-text');
    const detailsElement = document.getElementById('progress-details');
    
    if (!fillElement || !textElement || !detailsElement) return;
    
    // Update progress bar
    const percentage = Math.round(progress.progress || 0);
    fillElement.style.width = `${percentage}%`;
    
    // Update progress text
    let statusText = '';
    switch (progress.stage) {
        case 'parsing':
            statusText = `📄 Parsing file... (${percentage}%)`;
            break;
        case 'validating':
            statusText = `✅ Validating data... (${percentage}%)`;
            break;
        case 'categorizing':
            statusText = `🧠 AI Categorizing... (${percentage}%)`;
            break;
        case 'finalizing':
            statusText = `💾 Finalizing... (${percentage}%)`;
            break;
        case 'completed':
            statusText = '✅ Upload completed!';
            break;
        case 'failed':
            statusText = '❌ Upload failed';
            break;
        default:
            statusText = `Processing... (${percentage}%)`;
    }
    
    textElement.textContent = statusText;
    
    // Update details
    const details = [];
    if (progress.rows_processed !== undefined && progress.total_rows !== undefined) {
        details.push(`Processed: ${progress.rows_processed}/${progress.total_rows} rows`);
    }
    if (progress.staged_count !== undefined) {
        details.push(`Staged: ${progress.staged_count} transactions`);
    }
    if (progress.duplicate_count !== undefined && progress.duplicate_count > 0) {
        details.push(`Duplicates found: ${progress.duplicate_count}`);
    }
    if (progress.ml_suggestions_count !== undefined) {
        details.push(`AI suggestions: ${progress.ml_suggestions_count}`);
    }
    
    detailsElement.innerHTML = details.map(detail => `<div>• ${detail}</div>`).join('');
}

function hideUploadProgress() {
    const container = document.getElementById('upload-results');
    if (container) {
        container.classList.add('hidden');
        container.innerHTML = '';
    }
}

// ===== DRAG AND DROP SUPPORT =====
function setupDragAndDrop() {
    const uploadAreas = document.querySelectorAll('.upload-area');
    
    uploadAreas.forEach(area => {
        area.addEventListener('dragover', function(e) {
            e.preventDefault();
            area.classList.add('drag-over');
        });
        
        area.addEventListener('dragleave', function(e) {
            e.preventDefault();
            area.classList.remove('drag-over');
        });
        
        area.addEventListener('drop', function(e) {
            e.preventDefault();
            area.classList.remove('drag-over');
            
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                const file = files[0];
                
                // Determine which type of upload based on the area
                if (area.closest('#transactions-upload')) {
                    document.getElementById('transaction-file').files = files;
                    uploadTransactionFile();
                } else if (area.closest('#bootstrap-upload')) {
                    document.getElementById('bootstrap-file').files = files;
                    uploadBootstrapFile();
                }
            }
        });
    });
}

// ===== FILE INPUT LISTENERS =====
function setupFileInputListeners() {
    const transactionFileInput = document.getElementById('transaction-file');
    const bootstrapFileInput = document.getElementById('bootstrap-file');
    
    if (transactionFileInput) {
        transactionFileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                uploadTransactionFile();
            }
        });
    }
    
    if (bootstrapFileInput) {
        bootstrapFileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                uploadBootstrapFile();
            }
        });
    }
}

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', function() {
    setupDragAndDrop();
    setupFileInputListeners();
});

// Make functions globally available
window.uploadTransactionFile = uploadTransactionFile;
window.uploadBootstrapFile = uploadBootstrapFile;