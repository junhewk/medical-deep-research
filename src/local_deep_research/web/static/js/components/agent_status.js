/**
 * Agent Status Component
 *
 * Displays the status of the deep agent and any sub-agents.
 * Shows current tool being used, thinking indicator, and agent state.
 */

(function() {
    'use strict';

    /**
     * Agent Status Manager
     * @param {string} containerId - ID of the container element
     */
    function AgentStatus(containerId) {
        this.container = document.getElementById(containerId);
        this.agents = [];

        if (!this.container) {
            console.error('Agent status container not found:', containerId);
        }
    }

    /**
     * State display mapping
     */
    AgentStatus.prototype.stateDisplay = {
        idle: { text: 'Idle', class: 'state-idle', icon: 'fa-pause-circle' },
        planning: { text: 'Planning', class: 'state-planning', icon: 'fa-lightbulb' },
        running: { text: 'Running', class: 'state-running', icon: 'fa-play-circle' },
        waiting: { text: 'Waiting', class: 'state-waiting', icon: 'fa-hourglass-half' },
        completed: { text: 'Completed', class: 'state-completed', icon: 'fa-check-circle' },
        failed: { text: 'Failed', class: 'state-failed', icon: 'fa-times-circle' }
    };

    /**
     * Update the agent status display
     * @param {Array} agents - Array of agent status objects
     */
    AgentStatus.prototype.update = function(agents) {
        if (!this.container || !Array.isArray(agents)) return;

        this.agents = agents;
        this.render();
    };

    /**
     * Render all agent status cards
     */
    AgentStatus.prototype.render = function() {
        if (!this.container) return;

        // Clear container
        this.container.innerHTML = '';

        if (this.agents.length === 0) {
            // Show default agent card
            this.container.appendChild(this.createDefaultAgentCard());
            return;
        }

        // Render each agent
        this.agents.forEach(function(agent) {
            var agentCard = this.createAgentCard(agent);
            this.container.appendChild(agentCard);
        }, this);
    };

    /**
     * Create a default agent card when no agents are active
     * @returns {HTMLElement}
     */
    AgentStatus.prototype.createDefaultAgentCard = function() {
        var card = document.createElement('div');
        card.className = 'deep-agent-status-card';
        card.innerHTML = `
            <div class="deep-agent-status-header">
                <span class="deep-agent-name">Main Agent</span>
                <span class="deep-agent-state state-idle">Idle</span>
            </div>
            <div class="deep-agent-status-details">
                <div class="deep-agent-detail-row">
                    <span class="deep-agent-detail-label">Current Tool:</span>
                    <span class="deep-agent-detail-value">-</span>
                </div>
                <div class="deep-agent-detail-row">
                    <span class="deep-agent-detail-label">Status:</span>
                    <span class="deep-agent-detail-value">Initializing...</span>
                </div>
            </div>
        `;
        return card;
    };

    /**
     * Create an agent status card
     * @param {Object} agent - Agent data
     * @returns {HTMLElement}
     */
    AgentStatus.prototype.createAgentCard = function(agent) {
        var card = document.createElement('div');
        card.className = 'deep-agent-status-card';
        card.setAttribute('data-agent-name', agent.name || 'unknown');

        // Get state display info
        var status = agent.status || 'idle';
        var stateInfo = this.stateDisplay[status] || this.stateDisplay.idle;

        // Check if this is a sub-agent
        var isSubAgent = agent.parent_agent && agent.parent_agent !== '';

        // Build card HTML
        var html = `
            <div class="deep-agent-status-header">
                <span class="deep-agent-name">
                    ${isSubAgent ? '<i class="fas fa-level-down-alt"></i> ' : ''}
                    ${this.escapeHtml(agent.name || 'Agent')}
                </span>
                <span class="deep-agent-state ${stateInfo.class}">
                    <i class="fas ${stateInfo.icon}"></i>
                    ${stateInfo.text}
                </span>
            </div>
            <div class="deep-agent-status-details">
                <div class="deep-agent-detail-row">
                    <span class="deep-agent-detail-label">Current Tool:</span>
                    <span class="deep-agent-detail-value">${this.escapeHtml(agent.current_tool || '-')}</span>
                </div>
                <div class="deep-agent-detail-row">
                    <span class="deep-agent-detail-label">Status:</span>
                    <span class="deep-agent-detail-value">${this.escapeHtml(agent.message || 'Processing...')}</span>
                </div>
        `;

        // Add current step if available
        if (agent.current_step) {
            html += `
                <div class="deep-agent-detail-row">
                    <span class="deep-agent-detail-label">Current Step:</span>
                    <span class="deep-agent-detail-value">${this.escapeHtml(agent.current_step)}</span>
                </div>
            `;
        }

        // Add parent agent if sub-agent
        if (isSubAgent) {
            html += `
                <div class="deep-agent-detail-row deep-agent-parent-info">
                    <span class="deep-agent-detail-label">Parent:</span>
                    <span class="deep-agent-detail-value">${this.escapeHtml(agent.parent_agent)}</span>
                </div>
            `;
        }

        html += '</div>';

        // Add thinking indicator for running agents
        if (status === 'running' || status === 'planning') {
            html += `
                <div class="deep-agent-thinking-indicator">
                    <span class="deep-agent-thinking-dot"></span>
                    <span class="deep-agent-thinking-dot"></span>
                    <span class="deep-agent-thinking-dot"></span>
                </div>
            `;
        }

        card.innerHTML = html;
        return card;
    };

    /**
     * Update a single agent's status
     * @param {string} agentName - Agent name
     * @param {Object} updates - Fields to update
     */
    AgentStatus.prototype.updateAgent = function(agentName, updates) {
        var agent = this.agents.find(function(a) {
            return a.name === agentName;
        });

        if (agent) {
            Object.assign(agent, updates);
        } else {
            this.agents.push(Object.assign({ name: agentName }, updates));
        }
        this.render();
    };

    /**
     * Get the main agent
     * @returns {Object|null}
     */
    AgentStatus.prototype.getMainAgent = function() {
        return this.agents.find(function(agent) {
            return agent.name === 'main' || !agent.parent_agent;
        }) || this.agents[0] || null;
    };

    /**
     * Get sub-agents
     * @returns {Array}
     */
    AgentStatus.prototype.getSubAgents = function() {
        return this.agents.filter(function(agent) {
            return agent.parent_agent && agent.parent_agent !== '';
        });
    };

    /**
     * Check if any agent is running
     * @returns {boolean}
     */
    AgentStatus.prototype.isRunning = function() {
        return this.agents.some(function(agent) {
            return agent.status === 'running' || agent.status === 'planning';
        });
    };

    /**
     * Clear all agents
     */
    AgentStatus.prototype.clear = function() {
        this.agents = [];
        if (this.container) {
            this.container.appendChild(this.createDefaultAgentCard());
        }
    };

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string}
     */
    AgentStatus.prototype.escapeHtml = function(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };

    // Export to window
    window.AgentStatus = AgentStatus;

})();
