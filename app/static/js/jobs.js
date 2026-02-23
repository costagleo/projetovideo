/**
 * Jobs — lista de jobs, polling progress/ETA, logs
 */
const Jobs = {
    list: [],
    projectNames: {},
    pollInterval: null,

    async load() {
        // Preload project names for display
        try {
            const projects = await API.get('/api/projects');
            this.projectNames = {};
            projects.forEach(p => { this.projectNames[p.id] = p.name; });
        } catch {}
        await this.refresh();
        this.startPolling();
    },

    async refresh() {
        try {
            this.list = await API.get('/api/jobs');
            this.render();
        } catch (err) {
            Toast.error('Erro ao carregar processamentos: ' + err.message);
        }
    },

    render() {
        const container = document.getElementById('jobs-list');

        if (this.list.length === 0) {
            container.innerHTML = `
                <div class="text-center py-12">
                    <svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                    </svg>
                    <p class="text-gray-500">Nenhum processamento na fila</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.list.map(job => {
            const progress = Math.round(job.progress * 100);
            const eta = job.eta_s ? this.formatEta(job.eta_s) : '';
            const projectName = this.projectNames[job.project_id] || job.project_id.substring(0, 8) + '...';
            const isError = job.status === 'failed' || job.status === 'error';

            return `
                <div class="bg-gray-800 rounded-lg p-4 md:p-5 border border-gray-700">
                    <div class="flex items-center justify-between mb-2">
                        <div class="flex items-center gap-2 min-w-0">
                            <span class="text-sm font-medium truncate">${this.escapeHtml(projectName)}</span>
                            <span class="${Dashboard.statusBadgeClass(job.status)} flex-shrink-0">${Dashboard.statusLabel(job.status)}</span>
                        </div>
                        <div class="flex items-center gap-2 flex-shrink-0">
                            ${job.status === 'running' && eta ? `<span class="text-xs text-gray-400 hidden sm:inline">ETA: ${eta}</span>` : ''}
                            <button onclick="Jobs.showLog('${job.id}')" class="p-1.5 text-gray-400 hover:text-indigo-400 transition-colors" title="Ver log">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                                </svg>
                            </button>
                            <button onclick="Jobs.deleteJob('${job.id}')" class="p-1.5 text-gray-400 hover:text-red-400 transition-colors" title="Excluir">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                    ${job.status === 'running' || job.status === 'done' ? `
                    <div class="progress-bar mb-2">
                        <div class="progress-fill" style="width: ${progress}%"></div>
                    </div>
                    <div class="flex justify-between text-xs text-gray-500">
                        <span>${progress}%</span>
                        ${job.status === 'running' && eta ? `<span class="sm:hidden">ETA: ${eta}</span>` : ''}
                        <span>${Dashboard.timeAgo(job.created_at)}</span>
                    </div>
                    ` : ''}
                    ${isError && job.error_msg ? `
                    <p class="text-red-400 text-xs sm:text-sm mt-2 break-words">${this.escapeHtml(job.error_msg)}</p>
                    ` : ''}
                </div>
            `;
        }).join('');
    },

    startPolling() {
        if (this.pollInterval) clearInterval(this.pollInterval);

        const hasActive = this.list.some(j => j.status === 'queued' || j.status === 'running');
        if (hasActive) {
            this.pollInterval = setInterval(() => {
                if (Dashboard.currentPanel === 'jobs') {
                    this.refresh();
                } else {
                    clearInterval(this.pollInterval);
                    this.pollInterval = null;
                }
            }, 2500);
        }
    },

    async showLog(jobId) {
        document.getElementById('job-log-modal').classList.remove('hidden');
        document.getElementById('job-log-content').textContent = 'Carregando...';

        try {
            const data = await API.get(`/api/jobs/${jobId}/log`);
            document.getElementById('job-log-content').textContent = data.log || '(Log vazio)';
        } catch (err) {
            document.getElementById('job-log-content').textContent = 'Erro ao carregar log: ' + err.message;
        }
    },

    hideLog() {
        document.getElementById('job-log-modal').classList.add('hidden');
    },

    async deleteJob(jobId) {
        if (!await Dashboard.confirm('Excluir Processamento', 'Tem certeza que deseja excluir este item?')) return;
        try {
            await API.delete(`/api/jobs/${jobId}`);
            Toast.success('Processamento removido');
            this.refresh();
        } catch (err) {
            Toast.error(err.message);
        }
    },

    formatEta(seconds) {
        if (!seconds || seconds <= 0) return '';
        const min = Math.floor(seconds / 60);
        const sec = Math.floor(seconds % 60);
        if (min > 0) return `${min}m${sec}s`;
        return `${sec}s`;
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};
