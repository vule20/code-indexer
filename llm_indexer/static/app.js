document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const collectionsList = document.getElementById('collections-list');
    const indexForm = document.getElementById('index-form');
    const dirPathInput = document.getElementById('dir-path');
    const colNameInput = document.getElementById('col-name');
    const overwriteCheckbox = document.getElementById('overwrite-db');
    const btnIndex = document.getElementById('btn-index');
    
    const progressCard = document.getElementById('progress-card');
    const progressStatusText = document.getElementById('progress-status-text');
    const progressTime = document.getElementById('progress-time');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const statFiles = document.getElementById('stat-files');
    const statChunks = document.getElementById('stat-chunks');
    const statProcessed = document.getElementById('stat-processed');
    
    const activeCodebaseTitle = document.getElementById('active-codebase-title');
    const activeCodebaseSub = document.getElementById('active-codebase-sub');
    const numResultsSelect = document.getElementById('num-results-select');
    
    const emptyState = document.getElementById('empty-state');
    const messagesList = document.getElementById('messages-list');
    const chatInput = document.getElementById('chat-input');
    const btnSend = document.getElementById('btn-send');
    const chatForm = document.getElementById('chat-form');
    
    // Modal Elements
    const referenceModal = document.getElementById('reference-modal');
    const modalFileTitle = document.getElementById('modal-file-title');
    const modalFileSubtitle = document.getElementById('modal-file-subtitle');
    const modalCodeBlock = document.getElementById('modal-code-block');
    const btnCloseModal = document.getElementById('btn-close-modal');

    // App State
    let activeCollection = null;
    let isIndexing = false;
    let indexPollInterval = null;
    let chatHistory = [];

    // Theme Toggle
    const themeToggleBtn = document.getElementById('theme-toggle');
    const themeIcon = document.getElementById('theme-icon');
    if (localStorage.getItem('theme') === 'light') {
        document.body.classList.add('light-theme');
        themeIcon.setAttribute('data-lucide', 'moon');
    }

    // Initialize Lucide Icons
    lucide.createIcons();

    // Configure Marked.js options
    marked.setOptions({
        highlight: function(code, lang) {
            if (Prism.languages[lang]) {
                return Prism.highlight(code, Prism.languages[lang], lang);
            }
            return code;
        },
        breaks: true
    });

    // 1. Fetch Collections on Load
    fetchCollections();

    // 2. Poll indexing status on load in case a job is already running
    checkIndexingStatus();
    indexPollInterval = setInterval(checkIndexingStatus, 2000);

    // Event Listeners
    indexForm.addEventListener('submit', handleIndexSubmit);
    chatForm.addEventListener('submit', handleChatSubmit);
    btnSend.addEventListener('click', (e) => {
        e.preventDefault();
        if (chatInput.value.trim() && !btnSend.disabled) {
            chatForm.requestSubmit();
        }
    });
    btnCloseModal.addEventListener('click', () => referenceModal.classList.add('hidden'));
    
    // Suggestion Buttons
    document.querySelectorAll('.suggestion-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (activeCollection) {
                chatInput.value = btn.textContent;
                chatInput.focus();
                adjustTextareaHeight();
            }
        });
    });

    // Textarea Auto-height and Enter key handling
    chatInput.addEventListener('input', adjustTextareaHeight);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (chatInput.value.trim() && !btnSend.disabled) {
                chatForm.requestSubmit();
            }
        }
    });

    function adjustTextareaHeight() {
        chatInput.style.height = 'auto';
        chatInput.style.height = chatInput.scrollHeight + 'px';
    }

    // Modal click out to close
    window.addEventListener('click', (e) => {
        if (e.target === referenceModal) {
            referenceModal.classList.add('hidden');
        }
    });

    // Theme Toggle Handler
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', () => {
            document.body.classList.toggle('light-theme');
            const isLight = document.body.classList.contains('light-theme');
            localStorage.setItem('theme', isLight ? 'light' : 'dark');
            themeIcon.setAttribute('data-lucide', isLight ? 'moon' : 'sun');
            lucide.createIcons();
        });
    }

    // API Call: List Collections
    async function fetchCollections() {
        try {
            const res = await fetch('/api/collections');
            const data = await res.json();
            renderCollections(data.collections);
        } catch (err) {
            console.error('Error fetching collections:', err);
            collectionsList.innerHTML = `<div class="loading-text" style="color: var(--accent-error);">Failed to load collections</div>`;
        }
    }

    // Render Collections List
    function renderCollections(collections) {
        if (collections.length === 0) {
            collectionsList.innerHTML = `<div class="loading-text">No codebases indexed yet.</div>`;
            return;
        }

        collectionsList.innerHTML = '';
        collections.forEach(col => {
            const item = document.createElement('div');
            item.className = 'collection-item';
            if (activeCollection === col.name) item.classList.add('active');
            
            item.innerHTML = `
                <div class="col-name">${col.name}</div>
                <div class="col-count">${col.count} chunks</div>
            `;
            
            item.addEventListener('click', () => selectCollection(col.name, col.count));
            collectionsList.appendChild(item);
        });
    }

    // Select Active Codebase
    function selectCollection(name, count) {
        activeCollection = name;
        
        // Highlight active sidebar item
        document.querySelectorAll('.collection-item').forEach(item => {
            if (item.querySelector('.col-name').textContent === name) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        // Update header
        activeCodebaseTitle.textContent = name;
        activeCodebaseSub.textContent = `Indexed codebase containing ${count} context blocks`;

        // Enable chat controls
        chatInput.removeAttribute('disabled');
        btnSend.removeAttribute('disabled');
        chatInput.placeholder = `Ask a question about '${name}'...`;
        
        // Reset chat screen
        messagesList.innerHTML = '';
        messagesList.classList.add('hidden');
        emptyState.classList.remove('hidden');
        chatHistory = [];
        
        chatInput.focus();
    }

    // API Call: Trigger Indexing
    async function handleIndexSubmit(e) {
        e.preventDefault();
        if (isIndexing) return;

        const path = dirPathInput.value.trim();
        const name = colNameInput.value.trim();
        const overwrite = overwriteCheckbox.checked;

        btnIndex.disabled = true;
        btnIndex.innerHTML = `<i data-lucide="loader" class="animate-spin"></i> Indexing...`;
        lucide.createIcons();

        try {
            const res = await fetch('/api/index', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, name, overwrite })
            });

            if (!res.ok) {
                const errData = await res.json();
                alert(`Error: ${errData.detail}`);
                resetIndexButton();
                return;
            }

            isIndexing = true;
            progressCard.classList.remove('hidden');
            checkIndexingStatus();
            
        } catch (err) {
            console.error('Error starting indexing:', err);
            alert('Failed to connect to indexer API.');
            resetIndexButton();
        }
    }

    function resetIndexButton() {
        btnIndex.disabled = false;
        btnIndex.innerHTML = `<i data-lucide="hammer"></i> Build Index`;
        lucide.createIcons();
    }

    // API Call: Check Indexing Status (polling)
    async function checkIndexingStatus() {
        try {
            const res = await fetch('/api/index/status');
            const data = await res.json();
            
            if (data.status === 'idle') {
                isIndexing = false;
                progressCard.classList.add('hidden');
                resetIndexButton();
                return;
            }

            isIndexing = true;
            progressCard.classList.remove('hidden');
            btnIndex.disabled = true;
            btnIndex.innerHTML = `<i class="loading-spinner"></i> Indexing...`;

            // Update Progress Details
            progressStatusText.textContent = data.status.toUpperCase();
            progressTime.textContent = `${data.time_elapsed}s`;
            statFiles.textContent = data.total_files || '-';
            statChunks.textContent = data.total_chunks || '-';
            statProcessed.textContent = data.processed_chunks;

            // Calculate percentage
            if (data.total_chunks > 0) {
                const percent = Math.min(100, Math.round((data.processed_chunks / data.total_chunks) * 100));
                progressBarFill.style.width = `${percent}%`;
                progressStatusText.textContent = `${data.status.toUpperCase()} (${percent}%)`;
            } else {
                progressBarFill.style.width = '0%';
            }

            if (data.status === 'done') {
                isIndexing = false;
                progressStatusText.textContent = 'COMPLETE';
                progressBarFill.style.width = '100%';
                setTimeout(() => {
                    progressCard.classList.add('hidden');
                    resetIndexButton();
                    dirPathInput.value = '';
                    colNameInput.value = '';
                    overwriteCheckbox.checked = false;
                }, 3000);
                
                // Refresh list
                fetchCollections();
            } else if (data.status === 'error') {
                isIndexing = false;
                progressStatusText.textContent = 'FAILED';
                progressStatusText.style.color = 'var(--accent-error)';
                alert(`Indexing failed: ${data.error_message}`);
                setTimeout(() => {
                    progressCard.classList.add('hidden');
                    resetIndexButton();
                }, 4000);
            }

        } catch (err) {
            console.error('Error polling indexing status:', err);
        }
    }

    // Chat Form Submit (POST chat API and SSE Streaming)
    async function handleChatSubmit(e) {
        e.preventDefault();
        const message = chatInput.value.trim();
        if (!message || !activeCollection || isIndexing) return;

        // Reset input area
        chatInput.value = '';
        adjustTextareaHeight();
        
        // Hide empty state, show messages
        emptyState.classList.add('hidden');
        messagesList.classList.remove('hidden');

        // Append User Message
        appendMessage('user', message);

        // Append bot message container with Typing Indicator
        const botMsgDiv = appendMessage('bot', '');
        const bubble = botMsgDiv.querySelector('.message-bubble');
        bubble.innerHTML = `
            <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
            </div>
        `;
        
        // Disable input while generating
        chatInput.setAttribute('disabled', 'true');
        btnSend.setAttribute('disabled', 'true');

        try {
            const numResults = numResultsSelect.value;
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    collection: activeCollection,
                    message: message,
                    num_results: parseInt(numResults),
                    history: chatHistory
                })
            });

            if (!res.ok) {
                const errText = await res.text();
                throw new Error(errText || 'Failed to generate response.');
            }

            bubble.innerHTML = ''; // Clear typing indicator
            
            // Set up stream reader
            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            
            let accumulatedResponse = '';
            let references = [];
            let buffer = '';
            let currentEvent = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep last incomplete line

                for (const line of lines) {
                    const trimmedLine = line.trim();
                    if (!trimmedLine) continue;

                    if (trimmedLine.startsWith('event: ')) {
                        currentEvent = trimmedLine.substring(7).trim();
                    } else if (trimmedLine.startsWith('data: ')) {
                        const dataVal = trimmedLine.substring(6).trim();
                        
                        if (currentEvent === 'references') {
                            references = JSON.parse(dataVal);
                            renderReferences(botMsgDiv, references);
                        } else if (currentEvent === 'message') {
                            const chunk = JSON.parse(dataVal);
                            accumulatedResponse += chunk;
                            // Render Markdown
                            bubble.innerHTML = marked.parse(accumulatedResponse);
                            // Highlight newly rendered codeblocks
                            bubble.querySelectorAll('pre code').forEach((block) => {
                                Prism.highlightElement(block);
                            });
                            // Auto scroll chat window
                            messagesList.parentElement.scrollTop = messagesList.parentElement.scrollHeight;
                        }
                    }
                }
            }

            // Save conversation turns to chatHistory
            chatHistory.push({ role: 'user', content: message });
            chatHistory.push({ role: 'assistant', content: accumulatedResponse });

        } catch (err) {
            console.error('Chat stream error:', err);
            bubble.innerHTML = `<span style="color: var(--accent-error);">Error: ${err.message || 'Server connection issue.'}</span>`;
        } finally {
            // Re-enable input
            chatInput.removeAttribute('disabled');
            btnSend.removeAttribute('disabled');
            chatInput.focus();
        }
    }

    // Append Message Element
    function appendMessage(sender, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;
        
        msgDiv.innerHTML = `
            <div class="message-bubble">
                ${sender === 'user' ? escapeHTML(text) : text}
            </div>
        `;
        
        messagesList.appendChild(msgDiv);
        messagesList.parentElement.scrollTop = messagesList.parentElement.scrollHeight;
        return msgDiv;
    }

    // Render reference buttons under LLM response
    function renderReferences(messageDiv, references) {
        if (!references || references.length === 0) return;
        
        const refContainer = document.createElement('div');
        refContainer.className = 'references-container';
        
        refContainer.innerHTML = `<span class="references-label">REFERENCES:</span>`;
        
        const refList = document.createElement('div');
        refList.className = 'references-list';
        
        references.forEach(ref => {
            const tag = document.createElement('a');
            tag.className = 'reference-tag';
            tag.innerHTML = `<i data-lucide="file-text" style="width:12px; height:12px;"></i> [${ref.index}] ${ref.file_name}:${ref.start_line}-${ref.end_line}`;
            
            tag.addEventListener('click', (e) => {
                e.preventDefault();
                showReferenceModal(ref);
            });
            
            refList.appendChild(tag);
        });
        
        refContainer.appendChild(refList);
        messageDiv.appendChild(refContainer);
        lucide.createIcons();
    }

    // Open Reference modal and highlight
    function showReferenceModal(ref) {
        modalFileTitle.textContent = ref.file_name;
        modalFileSubtitle.textContent = `Path: ${ref.relative_path} | Lines: ${ref.start_line}-${ref.end_line} | Score: ${ref.score}`;
        
        // In order to make it look nice, map languages to prism classes
        let prismLang = 'cpp';
        if (ref.language === 'python') prismLang = 'python';
        else if (ref.language === 'cmake') prismLang = 'cmake';
        else if (ref.language === 'bash') prismLang = 'bash';
        else if (ref.language === 'markdown') prismLang = 'markdown';
        else if (ref.language === 'mlir') prismLang = 'mlir'; // prism handles it as plaintext mostly or C++ syntax fallback
        
        modalCodeBlock.className = `language-${prismLang}`;
        modalCodeBlock.textContent = ref.content;
        
        referenceModal.classList.remove('hidden');
        Prism.highlightElement(modalCodeBlock);
    }

    // Utility: Escape HTML
    function escapeHTML(str) {
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
});
