// static/js/uploads.js
// Enhanced upload system implementing 3-stage workflow:
// 1. Raw storage (immediate)
// 2. Configuration & processing 
// 3. Review & confirmation

// ===== GLOBAL STATE =====
let currentFileUpload = null;
let currentProcessingSession = null;

// ===== STAGE 1: RAW FILE UPLOAD =====

async function uploadRawFile(fileInput, fileType = 'transaction_data') {
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
    
    // Validate file size (100MB limit for raw storage)
    const maxSize = 100 * 1024 * 1024;
    if (file.size > maxSize) {
        showToast('❌ File too large. Maximum size is 100MB', 'error');
        return;
    }

    try {
        // Show immediate upload feedback
        showUploadProgress(`📤 Uploading ${file.name}...`, 0);
        updateConnectionStatus('reconnecting', 'Uploading file...');
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('file_purpose', fileType);
        
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
        currentFileUpload = result;
        
        // Clear the file input
        fileInput.value = '';
        
        // Show success and next steps
        hideUploadProgress();
        updateConnectionStatus('connected', 'File uploaded');
        
        if (result.duplicate) {
            showToast(`⚠️ File already uploaded: ${result.filename}`, 'warning');
            showFileManagement(result);
        } else {
            showToast(`✅ ${file.name} uploaded successfully!`, 'success');
            
            if (fileType === 'transaction_data') {
                showSchemaReview(result);
            } else {
                showTrainingDataConfiguration(result);
            }
        }
        
    } catch (error) {
        hideUploadProgress();
        updateConnectionStatus('disconnected', 'Upload failed');
        showToast(`❌ Upload failed: ${error.message}`, 'error');
        console.error('Upload error:', error);
    }
}

// ===== STAGE 1.5: SCHEMA REVIEW =====

function showSchemaReview(uploadResult) {
    const container = document.getElementById('upload-results');
    const schema = uploadResult.schema_detected;
    
    if (!schema || schema.error) {
        container.innerHTML = `
            <div class="upload-card error">
                <h3>❌ Schema Detection Failed</h3>
                <p>Could not automatically detect file structure.</p>
                <p class="error-detail">${schema?.error || 'Unknown error'}</p>
                <button class="btn btn-secondary" onclick="showManualConfiguration(${uploadResult.file_id})">
                    🛠️ Configure Manually
                </button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = `
        <div class="upload-card success">
            <h3>📋 File Schema Detected</h3>
            <div class="schema-info">
                <div class="file-stats">
                    <span class="stat">📄 ${uploadResult.filename}</span>
                    <span class="stat">📊 ${schema.row_count} rows</span>
                    <span class="stat">📋 ${schema.columns.length} columns</span>
                </div>
                
                <div class="columns-detected">
                    <h4>Columns Found:</h4>
                    <div class="column-list">
                        ${schema.columns.map(col => `
                            <span class="column-tag">${col}</span>
                        `).join('')}
                    </div>
                </div>
                
                <div class="sample-data">
                    <h4>Sample Data:</h4>
                    <div class="data-preview">
                        ${renderDataPreview(schema.sample_data)}
                    </div>
                </div>
                
                <div class="next-steps">
                    <h4>Next Steps:</h4>
                    <button class="btn btn-primary" onclick="startSmartConfiguration(${uploadResult.file_id})">
                        🤖 Smart Configuration
                    </button>
                    <button class="btn btn-secondary" onclick="startManualConfiguration(${uploadResult.file_id})">
                        🛠️ Manual Configuration
                    </button>
                </div>
            </div>
        </div>
    `;
}

function renderDataPreview(sampleData) {
    if (!sampleData || sampleData.length === 0) {
        return '<p>No sample data available</p>';
    }
    
    const headers = Object.keys(sampleData[0]);
    
    return `
        <table class="preview-table">
            <thead>
                <tr>
                    ${headers.map(h => `<th>${h}</th>`).join('')}
                </tr>
            </thead>
            <tbody>
                ${sampleData.map(row => `
                    <tr>
                        ${headers.map(h => `<td>${row[h] || ''}</td>`).join('')}
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// ===== STAGE 2: SMART CONFIGURATION =====

async function startSmartConfiguration(fileId) {
    try {
        showUploadProgress('🤖 Analyzing file structure...', 25);
        
        // Get available training datasets
        const trainingDatasets = await getTrainingDatasets();
        
        // Auto-detect column mappings  
        const columnMapping = await detectColumnMapping(fileId);
        
        showConfigurationInterface(fileId, {
            columnMapping,
            trainingDatasets,
            isSmartMode: true
        });
        
    } catch (error) {
        hideUploadProgress();
        showToast(`❌ Smart configuration failed: ${error.message}`, 'error');
    }
}

async function detectColumnMapping(fileId) {
    // Smart column detection logic
    const response = await makeAuthenticatedRequest(`${API_BASE}/upload/detect-columns/${fileId}`);
    
    if (response.ok) {
        return await response.json();
    }
    
    // Fallback to basic detection
    return {
        date: 'auto_detect',
        beneficiary: 'auto_detect', 
        amount: 'auto_detect',
        description: 'auto_detect'
    };
}

async function getTrainingDatasets() {
    try {
        const response = await makeAuthenticatedRequest(`${API_BASE}/upload/training/list`);
        
        if (response.ok) {
            const data = await response.json();
            return data.datasets;
        }
    } catch (error) {
        console.warn('Could not load training datasets:', error);
    }
    
    return [];
}

function showConfigurationInterface(fileId, config) {
    const container = document.getElementById('upload-results');
    
    container.innerHTML = `
        <div class="upload-card">
            <h3>⚙️ Processing Configuration</h3>
            
            <div class="config-section">
                <h4>Column Mapping</h4>
                <div class="column-mapping">
                    <div class="mapping-row">
                        <label>Date Column:</label>
                        <select id="date-column">
                            <option value="auto_detect">🤖 Auto-detect</option>
                            <option value="Date">Date</option>
                            <option value="Transaction Date">Transaction Date</option>
                            <option value="Started Date">Started Date</option>
                            <option value="Completed Date">Completed Date</option>
                        </select>
                    </div>
                    
                    <div class="mapping-row">
                        <label>Merchant/Beneficiary:</label>
                        <select id="beneficiary-column">
                            <option value="auto_detect">🤖 Auto-detect</option>
                            <option value="Beneficiary">Beneficiary</option>
                            <option value="Description">Description</option>
                            <option value="Merchant">Merchant</option>
                        </select>
                    </div>
                    
                    <div class="mapping-row">
                        <label>Amount Column:</label>
                        <select id="amount-column">
                            <option value="auto_detect">🤖 Auto-detect</option>
                            <option value="Amount">Amount</option>
                            <option value="Total">Total</option>
                            <option value="Value">Value</option>
                        </select>
                    </div>
                    
                    <div class="mapping-row">
                        <label>Description (Optional):</label>
                        <select id="description-column">
                            <option value="">None</option>
                            <option value="Description">Description</option>
                            <option value="Notes">Notes</option>
                            <option value="Memo">Memo</option>
                        </select>
                    </div>
                </div>
            </div>
            
            <div class="config-section">
                <h4>🧠 Training Data</h4>
                <div class="training-options">
                    <label class="checkbox-label">
                        <input type="checkbox" id="use-training-data" checked>
                        Use training data for smart categorization
                    </label>
                    
                    ${config.trainingDatasets.length > 0 ? `
                        <div class="training-datasets">
                            <label>Available datasets:</label>
                            ${config.trainingDatasets.map(dataset => `
                                <label class="checkbox-label">
                                    <input type="checkbox" value="${dataset.id}" checked>
                                    ${dataset.name} (${dataset.pattern_count} patterns)
                                </label>
                            `).join('')}
                        </div>
                    ` : `
                        <p class="info-text">
                            💡 No training data available yet. Upload your Hungarian 
                            categorized data to enable smart suggestions!
                        </p>
                    `}
                </div>
            </div>
            
            <div class="config-section">
                <h4>Processing Options</h4>
                <div class="processing-options">
                    <label class="checkbox-label">
                        <input type="checkbox" id="auto-approve-high-confidence" checked>
                        Auto-approve transactions with >90% confidence
                    </label>
                    
                    <div class="slider-option">
                        <label>Confidence Threshold: <span id="confidence-value">90%</span></label>
                        <input type="range" id="confidence-threshold" min="50" max="95" value="90" 
                               oninput="document.getElementById('confidence-value').textContent = this.value + '%'">
                    </div>
                </div>
            </div>
            
            <div class="action-buttons">
                <button class="btn btn-primary" onclick="startProcessing(${fileId})">
                    🚀 Start Processing
                </button>
                <button class="btn btn-secondary" onclick="saveConfigurationOnly(${fileId})">
                    💾 Save Configuration Only
                </button>
                <button class="btn btn-outline" onclick="showAdvancedOptions(${fileId})">
                    ⚙️ Advanced Options
                </button>
            </div>
        </div>
    `;
}

// ===== STAGE 2: PROCESSING =====

async function startProcessing(fileId) {
    try {
        // Collect configuration
        const config = {
            session_name: `Process ${new Date().toLocaleDateString()}`,
            column_mapping: {
                date: document.getElementById('date-column').value,
                beneficiary: document.getElementById('beneficiary-column').value,
                amount: document.getElementById('amount-column').value,
                description: document.getElementById('description-column').value
            },
            use_training_data: document.getElementById('use-training-data').checked,
            training_dataset_ids: Array.from(document.querySelectorAll('.training-datasets input:checked'))
                .map(cb => parseInt(cb.value)),
            processing_rules: {
                auto_approve_high_confidence: document.getElementById('auto-approve-high-confidence').checked,
                confidence_threshold: parseInt(document.getElementById('confidence-threshold').value) / 100
            }
        };
        
        showUploadProgress('⚙️ Configuring processing...', 10);
        
        // Step 1: Configure processing session
        const configResponse = await fetch(`${API_BASE}/upload/processing/configure/${fileId}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        });
        
        if (!configResponse.ok) {
            throw new Error('Configuration failed');
        }
        
        const configResult = await configResponse.json();
        currentProcessingSession = configResult.session_id;
        
        showUploadProgress('🚀 Starting processing...', 20);
        
        // Step 2: Start processing
        const processResponse = await fetch(`${API_BASE}/upload/processing/start/${configResult.session_id}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        
        if (!processResponse.ok) {
            throw new Error('Failed to start processing');
        }
        
        const processResult = await processResponse.json();
        
        showToast('🚀 Processing started!', 'success');
        updateConnectionStatus('connected', 'Processing transactions...');
        
        // Monitor processing progress
        monitorProcessingProgress(configResult.session_id);
        
    } catch (error) {
        hideUploadProgress();
        showToast(`❌ Processing failed: ${error.message}`, 'error');
        updateConnectionStatus('disconnected', 'Processing failed');
    }
}

async function monitorProcessingProgress(sessionId) {
    const maxAttempts = 180; // 3 minutes max
    let attempts = 0;
    
    const checkProgress = async () => {
        try {
            const response = await makeAuthenticatedRequest(
                `${API_BASE}/upload/processing/status/${sessionId}`
            );
            
            if (response.ok) {
                const progress = await response.json();
                
                // Update progress UI
                const percentage = Math.min(95, (progress.rows_processed / progress.total_rows_found) * 95);
                showUploadProgress(
                    `⚙️ Processing: ${progress.rows_processed}/${progress.total_rows_found} rows`, 
                    percentage
                );
                
                if (progress.status === 'processed') {
                    hideUploadProgress();
                    updateConnectionStatus('connected', 'Processing complete');
                    showToast(`✅ Processing complete! ${progress.rows_with_suggestions} suggestions generated`, 'success');
                    
                    // Show review interface
                    showTransactionReview(sessionId);
                    return;
                    
                } else if (progress.status === 'failed') {
                    hideUploadProgress();
                    updateConnectionStatus('disconnected', 'Processing failed');
                    showToast(`❌ Processing failed: ${progress.error || 'Unknown error'}`, 'error');
                    return;
                }
                
                // Continue monitoring
                if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(checkProgress, 1000);
                } else {
                    hideUploadProgress();
                    updateConnectionStatus('disconnected', 'Processing timeout');
                    showToast('❌ Processing timed out', 'error');
                }
                
            } else {
                throw new Error('Could not check progress');
            }
            
        } catch (error) {
            hideUploadProgress();
            updateConnectionStatus('disconnected', 'Monitoring failed');
            showToast(`❌ Progress monitoring failed: ${error.message}`, 'error');
        }
    };
    
    checkProgress();
}

// ===== STAGE 3: TRANSACTION REVIEW =====

async function showTransactionReview(sessionId) {
    try {
        const response = await makeAuthenticatedRequest(
            `${API_BASE}/upload/processed/${sessionId}`
        );
        
        if (!response.ok) {
            throw new Error('Could not load transactions');
        }
        
        const data = await response.json();
        renderTransactionReview(data.transactions, sessionId);
        
    } catch (error) {
        showToast(`❌ Could not load transactions: ${error.message}`, 'error');
    }
}

function renderTransactionReview(transactions, sessionId) {
    const container = document.getElementById('upload-results');
    
    const highConfidence = transactions.filter(t => t.confidence >= 0.9);
    const needsReview = transactions.filter(t => t.confidence < 0.9);
    
    container.innerHTML = `
        <div class="upload-card">
            <h3>📋 Transaction Review</h3>
            
            <div class="review-stats">
                <div class="stat-card">
                    <span class="stat-number">${transactions.length}</span>
                    <span class="stat-label">Total Transactions</span>
                </div>
                <div class="stat-card success">
                    <span class="stat-number">${highConfidence.length}</span>
                    <span class="stat-label">High Confidence</span>
                </div>
                <div class="stat-card warning">
                    <span class="stat-number">${needsReview.length}</span>
                    <span class="stat-label">Needs Review</span>
                </div>
            </div>
            
            <div class="review-actions">
                <button class="btn btn-success" onclick="approveAllHighConfidence(${sessionId})">
                    ✅ Approve ${highConfidence.length} High-Confidence
                </button>
                <button class="btn btn-primary" onclick="showDetailedReview(${sessionId})">
                    📋 Review All Transactions
                </button>
                <button class="btn btn-secondary" onclick="exportForManualReview(${sessionId})">
                    📥 Export for Manual Review
                </button>
            </div>
        </div>
    `;
}

// ===== TRAINING DATA UPLOAD =====

function showTrainingDataConfiguration(uploadResult) {
    const container = document.getElementById('upload-results');
    
    container.innerHTML = `
        <div class="upload-card">
            <h3>🧠 Training Data Configuration</h3>
            <p>Configure how to extract patterns from your categorized data.</p>
            
            <div class="config-section">
                <h4>Column Mapping</h4>
                <p class="info-text">Tell us which columns contain what information:</p>
                
                <div class="column-mapping">
                    <div class="mapping-row">
                        <label>Merchant/Beneficiary Column:</label>
                        <select id="training-merchant-column">
                            <option value="Beneficiary">Beneficiary</option>
                            <option value="Merchant">Merchant</option>
                            <option value="Description">Description</option>
                        </select>
                    </div>
                    
                    <div class="mapping-row">
                        <label>Category Column (Hungarian):</label>
                        <select id="training-category-column">
                            <option value="Category">Category</option>
                            <option value="Kategória">Kategória</option>
                            <option value="Type">Type</option>
                        </select>
                    </div>
                    
                    <div class="mapping-row">
                        <label>Amount Column (Optional):</label>
                        <select id="training-amount-column">
                            <option value="">None</option>
                            <option value="Amount">Amount</option>
                            <option value="Összeg">Összeg</option>
                        </select>
                    </div>
                </div>
            </div>
            
            <div class="config-section">
                <h4>Category Mapping</h4>
                <p class="info-text">Map Hungarian categories to English:</p>
                <div class="category-mapping">
                    <textarea id="category-mapping" rows="8" placeholder="Enter mappings like:
ruha: Clothing
kávé: Food & Beverage
háztartás: Household
autó: Transportation
..."></textarea>
                </div>
            </div>
            
            <div class="action-buttons">
                <button class="btn btn-primary" onclick="createTrainingDataset(${uploadResult.file_id})">
                    🚀 Create Training Dataset
                </button>
                <button class="btn btn-secondary" onclick="previewTrainingData(${uploadResult.file_id})">
                    👁️ Preview Data
                </button>
            </div>
        </div>
    `;
}

async function createTrainingDataset(fileId) {
    try {
        // Parse category mapping
        const mappingText = document.getElementById('category-mapping').value;
        const categoryMapping = {};
        
        mappingText.split('\n').forEach(line => {
            const [hungarian, english] = line.split(':').map(s => s.trim());
            if (hungarian && english) {
                categoryMapping[hungarian] = english;
            }
        });
        
        const config = {
            name: `Training Data ${new Date().toLocaleDateString()}`,
            column_mapping: {
                merchant: document.getElementById('training-merchant-column').value,
                category: document.getElementById('training-category-column').value,
                amount: document.getElementById('training-amount-column').value
            },
            category_mapping: categoryMapping,
            language: 'hu'
        };
        
        showUploadProgress('🧠 Extracting patterns...', 50);
        
        const response = await fetch(`${API_BASE}/upload/training/create/${fileId}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        });
        
        if (!response.ok) {
            throw new Error('Training dataset creation failed');
        }
        
        const result = await response.json();
        
        hideUploadProgress();
        showToast(`✅ Training dataset created! ${result.patterns_extracted} patterns extracted`, 'success');
        
        // Show success summary
        showTrainingDataSuccess(result);
        
    } catch (error) {
        hideUploadProgress();
        showToast(`❌ Training dataset creation failed: ${error.message}`, 'error');
    }
}

function showTrainingDataSuccess(result) {
    const container = document.getElementById('upload-results');
    
    container.innerHTML = `
        <div class="upload-card success">
            <h3>✅ Training Dataset Created</h3>
            
            <div class="success-stats">
                <div class="stat-card">
                    <span class="stat-number">${result.patterns_extracted}</span>
                    <span class="stat-label">Total Patterns</span>
                </div>
                <div class="stat-card">
                    <span class="stat-number">${result.merchant_patterns}</span>
                    <span class="stat-label">Merchant Patterns</span>
                </div>
                <div class="stat-card">
                    <span class="stat-number">${result.category_mappings}</span>
                    <span class="stat-label">Categories Mapped</span>
                </div>
            </div>
            
            <p class="success-message">
                🎉 Your training data is now ready! Future transaction uploads will use 
                these patterns for intelligent categorization suggestions.
            </p>
            
            <div class="next-steps">
                <button class="btn btn-primary" onclick="loadMainApplication()">
                    🚀 Start Using the App
                </button>
                <button class="btn btn-secondary" onclick="uploadMoreFiles()">
                    📤 Upload More Files
                </button>
            </div>
        </div>
    `;
}

// ===== FILE INPUT LISTENERS (Updated) =====

function setupFileInputListeners() {
    const transactionFileInput = document.getElementById('transaction-file');
    const trainingFileInput = document.getElementById('bootstrap-file');
    
    if (transactionFileInput) {
        transactionFileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                uploadRawFile(this, 'transaction_data');
            }
        });
    }
    
    if (trainingFileInput) {
        trainingFileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                uploadRawFile(this, 'training_data');
            }
        });
    }
}

// ===== PROGRESS UI =====

function showUploadProgress(message, percentage = 0) {
    const container = document.getElementById('upload-results');
    container.innerHTML = `
        <div class="upload-progress">
            <div class="progress-header">
                <span class="progress-text">${message}</span>
                <span class="progress-percentage">${Math.round(percentage)}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${percentage}%"></div>
            </div>
        </div>
    `;
}

function hideUploadProgress() {
    const container = document.getElementById('upload-results');
    if (container) {
        container.innerHTML = '';
    }
}

// ===== UTILITY FUNCTIONS =====

function loadMainApplication() {
    // Switch to main app tabs
    switchTab('staged');
    loadStagedTransactionsPaginated();
}

function uploadMoreFiles() {
    // Clear current state and allow new uploads
    currentFileUpload = null;
    currentProcessingSession = null;
    hideUploadProgress();
}

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', function() {
    setupFileInputListeners();
});

// Make functions globally available
window.uploadRawFile = uploadRawFile;
window.startSmartConfiguration = startSmartConfiguration;
window.startProcessing = startProcessing;
window.createTrainingDataset = createTrainingDataset;