document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('summarize-form');
    const urlInput = document.getElementById('youtube-url');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = submitBtn.querySelector('.btn-text');
    const loader = submitBtn.querySelector('.loader');
    const errorMsg = document.getElementById('error-message');
    const resultsSection = document.getElementById('results-section');
    const summaryContent = document.getElementById('summary-content');

    // Company branding
    const COMPANY_URL = 'https://learnfast.ai';

    // Generate or retrieve User ID
    let userId = localStorage.getItem('yt_summarizer_user_id');
    if (!userId) {
        userId = 'user_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
        localStorage.setItem('yt_summarizer_user_id', userId);
    }

    // Navigation Links (Update to real URLs)
    const navLibrary = document.getElementById('nav-library');
    if (navLibrary) {
        navLibrary.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.href = '/library';
        });
    }

    // Deep Link Handling (Check for ?v=videoId)
    const urlParams = new URLSearchParams(window.location.search);
    const deepVideoId = urlParams.get('v');
    if (deepVideoId) {
        const videoUrl = `https://www.youtube.com/watch?v=${deepVideoId}`;
        urlInput.value = videoUrl;
        
        // Try to load from cache immediately for instant display
        fetch(`/api/video/${deepVideoId}`)
            .then(res => res.json())
            .then(data => {
                if (data && data.summary_text) {
                    // Update metadata
                    const titleEl = document.getElementById('video-title');
                    const channelEl = document.getElementById('channel-name');
                    const thumbEl = document.getElementById('video-thumbnail');
                    const metaContainer = document.getElementById('metadata-container');
                    
                    if (titleEl) titleEl.textContent = data.title;
                    if (channelEl) channelEl.textContent = data.channel_name;
                    if (thumbEl) thumbEl.src = data.thumbnail_url || `/api/thumbnail/${deepVideoId}`;
                    if (metaContainer) metaContainer.classList.remove('hidden');
                    
                    // Render result
                    summaryContent.innerHTML = marked.parse(data.summary_text);
                    if (data.tags_text) {
                        summaryContent.innerHTML += `
                            <div class="tags-section">
                                <div class="tags-container">
                                    ${data.tags_text.split(',').map(tag => `<span class="tag-chip">${tag.trim()}</span>`).join('')}
                                </div>
                            </div>
                        `;
                    }
                    resultsSection.classList.remove('hidden');
                } else {
                    // Fallback to normal summarize if not fully cached
                    form.dispatchEvent(new Event('submit'));
                }
            })
            .catch(() => {
                form.dispatchEvent(new Event('submit'));
            });
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const url = urlInput.value.trim();
        if (!url) return;

        const templateType = document.querySelector('input[name="template_type"]:checked').value;
        const templateLabel = document.querySelector('input[name="template_type"]:checked').nextElementSibling.textContent;

        // Reset UI
        errorMsg.classList.add('hidden');
        resultsSection.classList.add('hidden');
        summaryContent.innerHTML = '';
        
        // Set Loading State
        submitBtn.disabled = true;
        btnText.classList.add('hidden');
        loader.classList.remove('hidden');

        try {
            const response = await fetch('/api/summarize', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url, template_type: templateType, user_id: userId })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'An error occurred while summarizing the video.');
            }

            // Update Title
            document.getElementById('results-title').textContent = templateLabel;

            // Render Metadata
            const metadataContainer = document.getElementById('video-metadata');
            if (data.title || data.channel_name || data.video_id) {
                document.getElementById('meta-title').textContent = data.title || 'Unknown Title';
                document.getElementById('meta-channel').textContent = data.channel_name || 'Unknown Channel';
                
                // Load thumbnail from backend
                const thumbImg = document.getElementById('meta-thumbnail');
                if (data.video_id) {
                    thumbImg.src = `/api/thumbnail/${data.video_id}`;
                    thumbImg.style.display = 'block';
                    // Fallback to original url if our backend doesn't have it
                    thumbImg.onerror = () => {
                        if (data.thumbnail_url && thumbImg.src !== data.thumbnail_url) {
                            thumbImg.src = data.thumbnail_url;
                        } else {
                            thumbImg.style.display = 'none';
                        }
                    };
                } else {
                    thumbImg.style.display = 'none';
                }
                metadataContainer.classList.remove('hidden');
            } else {
                metadataContainer.classList.add('hidden');
            }

            // Helper to render tags as chips
            const renderTags = (rawTagsString) => {
                let rawTags = rawTagsString;
                // Remove common LLM prefixes
                rawTags = rawTags.replace(/^(Tags|Keywords|Result|Here are the tags):?\s*/i, '');
                // Split by common delimiters
                const tags = rawTags
                    .split(/,|\n|;|•|\*|-/)
                    .map(tag => tag.trim())
                    .map(tag => tag.replace(/^\d+\.\s*/, ''))
                    .map(tag => tag.replace(/\*\*|__/g, ''))
                    .filter(tag => tag && tag.length > 1 && tag.length < 50);

                if (tags.length > 0) {
                    return `
                        <div class="tags-container">
                            ${tags.map(tag => `<span class="tag-chip">${tag}</span>`).join('')}
                        </div>
                    `;
                }
                return marked.parse(rawTagsString);
            };

            // Render Result
            let htmlContent = '';
            if (templateType === 'tags') {
                htmlContent = renderTags(data.summary);
            } else {
                htmlContent = marked.parse(data.summary);
                if (data.tags) {
                    htmlContent += `
                        <div class="tags-section">
                            ${renderTags(data.tags)}
                        </div>
                    `;
                }
            }

            summaryContent.innerHTML = htmlContent;
            summaryContent.dataset.rawMarkdown = data.summary; // Store raw markdown for copying
            resultsSection.classList.remove('hidden');

            // Render Transcript
            const transcriptContainer = document.getElementById('transcript-container');
            const transcriptContent = document.getElementById('transcript-content');
            if (data.transcript) {
                const videoUrl = `https://www.youtube.com/watch?v=${data.video_id}`;
                const header = [
                    `LearnFast.ai | ${COMPANY_URL}`,
                    `Video : ${data.title || 'Unknown Title'}`,
                    `URL   : ${videoUrl}`,
                    '─'.repeat(60),
                    ''
                ].join('\n');

                transcriptContent.textContent = header + data.transcript;
                transcriptContent.dataset.rawTranscript = header + data.transcript;
                transcriptContainer.style.display = 'block';
                transcriptContainer.removeAttribute('open'); // start collapsed
            } else {
                transcriptContainer.style.display = 'none';
            }
            
            // Smooth scroll to results
            resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        } catch (error) {
            errorMsg.textContent = error.message;
            errorMsg.classList.remove('hidden');
        } finally {
            // Reset Loading State
            submitBtn.disabled = false;
            btnText.classList.remove('hidden');
            loader.classList.add('hidden');
        }
    });

    const copyBtn = document.getElementById('copy-btn');
    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            const rawMarkdown = summaryContent.dataset.rawMarkdown;
            if (rawMarkdown) {
                navigator.clipboard.writeText(rawMarkdown).then(() => {
                    const originalText = copyBtn.textContent;
                    copyBtn.textContent = 'Copied!';
                    setTimeout(() => {
                        copyBtn.textContent = originalText;
                    }, 2000);
                }).catch(err => {
                    console.error('Failed to copy!', err);
                });
            }
        });
    }

    // Copy Transcript
    const copyTranscriptBtn = document.getElementById('copy-transcript-btn');
    if (copyTranscriptBtn) {
        copyTranscriptBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const text = document.getElementById('transcript-content').dataset.rawTranscript
                       || document.getElementById('transcript-content').textContent;
            if (text) {
                navigator.clipboard.writeText(text).then(() => {
                    const origHTML = copyTranscriptBtn.innerHTML;
                    copyTranscriptBtn.textContent = '✅ Copied!';
                    setTimeout(() => { copyTranscriptBtn.innerHTML = origHTML; }, 2000);
                });
            }
        });
    }

    // Download Transcript
    const downloadTranscriptBtn = document.getElementById('download-transcript-btn');
    if (downloadTranscriptBtn) {
        downloadTranscriptBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const text = document.getElementById('transcript-content').dataset.rawTranscript
                       || document.getElementById('transcript-content').textContent;
            const title = document.getElementById('meta-title').textContent || 'transcript';
            if (text) {
                const blob = new Blob([text], { type: 'text/plain' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${title.replace(/[^a-z0-9]/gi, '_')}_transcript.txt`;
                a.click();
                URL.revokeObjectURL(url);
            }
        });
    }
    // Global helper for task buttons
    window.generateSpecific = (type) => {
        const radio = document.querySelector(`input[name="template_type"][value="${type}"]`);
        if (radio) {
            radio.checked = true;
            form.dispatchEvent(new Event('submit'));
        }
    };
});
