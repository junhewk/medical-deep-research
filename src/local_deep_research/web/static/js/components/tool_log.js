/**
 * Tool Log Component
 *
 * Displays a chronological log of tool executions from the deep agent.
 * Shows tool name, status, duration, and expandable details.
 */

(function() {
    'use strict';

    /**
     * Tool Log Manager
     * @param {string} containerId - ID of the container element
     */
    function ToolLog(containerId) {
        this.container = document.getElementById(containerId);
        this.executions = [];
        this.template = document.getElementById('tool-execution-template');
        this.filter = 'all'; // all, running, completed, failed

        if (!this.container) {
            console.error('Tool log container not found:', containerId);
        }
    }

    /**
     * Status icon mapping
     */
    ToolLog.prototype.statusIcons = {
        running: 'fa-spinner fa-spin',
        completed: 'fa-check',
        failed: 'fa-times'
    };

    /**
     * Status class mapping
     */
    ToolLog.prototype.statusClasses = {
        running: 'tool-running',
        completed: 'tool-completed',
        failed: 'tool-failed'
    };

    /**
     * Tool display names and icons
     */
    ToolLog.prototype.toolInfo = {
        pico_query_builder: { name: 'PICO Query Builder', icon: 'fa-microscope' },
        pico_query: { name: 'PICO Query', icon: 'fa-microscope' },
        pico: { name: 'PICO Analysis', icon: 'fa-microscope' },
        mesh_term_mapping: { name: 'MeSH Mapping', icon: 'fa-tags' },
        mesh_mapping: { name: 'MeSH Mapping', icon: 'fa-tags' },
        mesh: { name: 'MeSH Terms', icon: 'fa-tags' },
        pubmed_search: { name: 'PubMed Search', icon: 'fa-search' },
        pubmed: { name: 'PubMed', icon: 'fa-search' },
        search: { name: 'Search', icon: 'fa-search' },
        evidence_classifier: { name: 'Evidence Classification', icon: 'fa-layer-group' },
        evidence_classification: { name: 'Evidence Classification', icon: 'fa-layer-group' },
        evidence: { name: 'Evidence Analysis', icon: 'fa-layer-group' },
        citation_formatter: { name: 'Citation Formatter', icon: 'fa-quote-right' },
        synthesis: { name: 'Synthesis', icon: 'fa-brain' },
        synthesize: { name: 'Synthesis', icon: 'fa-brain' }
    };

    /**
     * Update the tool log display
     * @param {Array} executions - Array of tool execution objects
     */
    ToolLog.prototype.update = function(executions) {
        if (!this.container || !Array.isArray(executions)) return;

        this.executions = executions;
        this.render();
    };

    /**
     * Add a single execution
     * @param {Object} execution - Tool execution object
     */
    ToolLog.prototype.add = function(execution) {
        if (!execution) return;

        // Check if this execution already exists (update it)
        var existingIndex = this.findExecutionIndex(execution);
        if (existingIndex >= 0) {
            this.executions[existingIndex] = execution;
        } else {
            this.executions.push(execution);
        }

        this.render();
    };

    /**
     * Find execution index by matching tool and start time
     * @param {Object} execution - Execution to find
     * @returns {number} Index or -1 if not found
     */
    ToolLog.prototype.findExecutionIndex = function(execution) {
        return this.executions.findIndex(function(ex) {
            return ex.tool === execution.tool && ex.started_at === execution.started_at;
        });
    };

    /**
     * Render all tool executions
     */
    ToolLog.prototype.render = function() {
        if (!this.container) return;

        // Clear container
        this.container.innerHTML = '';

        // Filter executions
        var filtered = this.getFilteredExecutions();

        if (filtered.length === 0) {
            this.container.innerHTML = `
                <div class="deep-agent-tool-log-empty">
                    <i class="fas fa-clock"></i>
                    <span>Waiting for tool executions...</span>
                </div>
            `;
            return;
        }

        // Create entries (newest first)
        var reversed = filtered.slice().reverse();
        reversed.forEach(function(execution) {
            var entry = this.createExecutionEntry(execution);
            this.container.appendChild(entry);
        }, this);
    };

    /**
     * Get filtered executions based on current filter
     * @returns {Array}
     */
    ToolLog.prototype.getFilteredExecutions = function() {
        if (this.filter === 'all') {
            return this.executions;
        }
        var filter = this.filter;
        return this.executions.filter(function(ex) {
            return ex.status === filter;
        });
    };

    /**
     * Create a tool execution entry element
     * @param {Object} execution - Execution data
     * @returns {HTMLElement}
     */
    ToolLog.prototype.createExecutionEntry = function(execution) {
        var entry;

        // Try to use template
        if (this.template) {
            entry = document.importNode(this.template.content, true).firstElementChild;
        } else {
            entry = document.createElement('div');
            entry.className = 'deep-agent-tool-entry';
            entry.innerHTML = `
                <div class="deep-agent-tool-time"></div>
                <div class="deep-agent-tool-name"></div>
                <div class="deep-agent-tool-status">
                    <span class="deep-agent-tool-status-icon"></span>
                </div>
                <div class="deep-agent-tool-details"></div>
            `;
        }

        // Get status info
        var status = execution.status || 'running';
        var statusClass = this.statusClasses[status] || 'tool-running';
        var statusIcon = this.statusIcons[status] || 'fa-spinner fa-spin';

        // Get tool info
        var toolKey = (execution.tool || 'unknown').toLowerCase();
        var toolInfo = this.toolInfo[toolKey] || { name: execution.tool, icon: 'fa-cog' };

        // Set data attribute
        entry.setAttribute('data-tool', execution.tool || '');
        entry.classList.add(statusClass);

        // Update time
        var timeEl = entry.querySelector('.deep-agent-tool-time');
        if (timeEl) {
            var time = execution.started_at ? this.formatTime(execution.started_at) : 'Now';
            timeEl.textContent = time;
        }

        // Update tool name
        var nameEl = entry.querySelector('.deep-agent-tool-name');
        if (nameEl) {
            nameEl.innerHTML = `
                <i class="fas ${toolInfo.icon}"></i>
                <span>${this.escapeHtml(toolInfo.name)}</span>
            `;
        }

        // Update status icon
        var statusIconEl = entry.querySelector('.deep-agent-tool-status-icon');
        if (statusIconEl) {
            statusIconEl.innerHTML = `<i class="fas ${statusIcon}"></i>`;

            // Add duration if completed
            if (status === 'completed' && execution.duration_ms) {
                var seconds = (execution.duration_ms / 1000).toFixed(1);
                statusIconEl.innerHTML += ` <span class="deep-agent-tool-duration">(${seconds}s)</span>`;
            }
        }

        // Update details
        var detailsEl = entry.querySelector('.deep-agent-tool-details');
        if (detailsEl) {
            var details = [];

            if (execution.query) {
                var queryPreview = execution.query.length > 60
                    ? execution.query.substring(0, 60) + '...'
                    : execution.query;
                details.push(this.escapeHtml(queryPreview));
            }

            if (execution.error) {
                details.push('<span class="deep-agent-tool-error">' + this.escapeHtml(execution.error) + '</span>');
            }

            if (execution.result_preview) {
                details.push('<span class="deep-agent-tool-result">' + this.escapeHtml(execution.result_preview) + '</span>');
            }

            detailsEl.innerHTML = details.join(' ');

            // Make clickable for expand if has query
            if (execution.query && execution.query.length > 60) {
                detailsEl.classList.add('expandable');
                detailsEl.setAttribute('title', 'Click to expand');
                detailsEl.onclick = function() {
                    this.classList.toggle('expanded');
                    if (this.classList.contains('expanded')) {
                        this.innerHTML = '<span class="full-query">' + this.parentNode._fullQuery + '</span>';
                    } else {
                        var short = this.parentNode._fullQuery.substring(0, 60) + '...';
                        this.innerHTML = '<span>' + short + '</span>';
                    }
                };
                entry._fullQuery = this.escapeHtml(execution.query);
            }
        }

        return entry;
    };

    /**
     * Set filter
     * @param {string} filter - Filter type (all, running, completed, failed)
     */
    ToolLog.prototype.setFilter = function(filter) {
        this.filter = filter;
        this.render();
    };

    /**
     * Get execution counts by status
     * @returns {Object}
     */
    ToolLog.prototype.getCounts = function() {
        var counts = { all: this.executions.length, running: 0, completed: 0, failed: 0 };

        this.executions.forEach(function(ex) {
            if (counts.hasOwnProperty(ex.status)) {
                counts[ex.status]++;
            }
        });

        return counts;
    };

    /**
     * Get running executions
     * @returns {Array}
     */
    ToolLog.prototype.getRunning = function() {
        return this.executions.filter(function(ex) {
            return ex.status === 'running';
        });
    };

    /**
     * Clear the log
     */
    ToolLog.prototype.clear = function() {
        this.executions = [];
        if (this.container) {
            this.container.innerHTML = `
                <div class="deep-agent-tool-log-empty">
                    <i class="fas fa-clock"></i>
                    <span>Waiting for tool executions...</span>
                </div>
            `;
        }
    };

    /**
     * Format ISO timestamp to local time
     * @param {string} isoTime - ISO timestamp
     * @returns {string}
     */
    ToolLog.prototype.formatTime = function(isoTime) {
        try {
            var date = new Date(isoTime);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch (e) {
            return 'Unknown';
        }
    };

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string}
     */
    ToolLog.prototype.escapeHtml = function(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };

    // Export to window
    window.ToolLog = ToolLog;

})();
