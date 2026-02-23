/**
 * Downloads — listagem outputs, download individual + ZIP
 */
const Downloads = {
    projects: [],

    async load() {
        try {
            this.projects = await API.get('/api/projects');
            await this.loadOutputs();
        } catch (err) {
            Toast.error('Erro ao carregar downloads: ' + err.message);
        }
    },

    async loadOutputs() {
        const container = document.getElementById('downloads-list');
        if (this.projects.length === 0) {
            container.innerHTML = `
                <div class="text-center py-12">
                    <svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                    </svg>
                    <p class="text-gray-500">Nenhum projeto disponível</p>
                </div>
            `;
            return;
        }

        // Load outputs for each project
        const projectOutputs = [];
        for (const project of this.projects) {
            try {
                const outputs = await API.get(`/api/projects/${project.id}/outputs`);
                if (outputs && outputs.length > 0) {
                    projectOutputs.push({ project, outputs });
                }
            } catch {
                // Project may not have outputs yet
            }
        }

        if (projectOutputs.length === 0) {
            container.innerHTML = `
                <div class="text-center py-12">
                    <svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                    </svg>
                    <p class="text-gray-500">Nenhum vídeo renderizado ainda</p>
                </div>
            `;
            return;
        }

        container.innerHTML = projectOutputs.map(({ project, outputs }) => `
            <div class="bg-gray-800 rounded-lg p-5 border border-gray-700">
                <h3 class="font-semibold mb-3">${this.escapeHtml(project.name)}</h3>
                <div class="space-y-2">
                    ${outputs.map(output => `
                        <div class="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg">
                            <div class="flex items-center gap-2">
                                <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                </svg>
                                <span class="text-sm">${this.escapeHtml(output.name)}</span>
                                <span class="text-xs text-gray-500">${this.formatSize(output.size)}</span>
                            </div>
                            <button onclick="Downloads.downloadFile('${project.id}', '${encodeURIComponent(output.name)}')"
                                class="px-3 py-1 bg-indigo-600 hover:bg-indigo-700 rounded text-xs font-medium transition-colors">
                                Baixar
                            </button>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');
    },

    async downloadFile(projectId, filename) {
        try {
            Toast.info('Iniciando download...');
            const blob = await API.downloadBlob(`/api/outputs/${projectId}/${filename}/download`);
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = decodeURIComponent(filename);
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (err) {
            Toast.error('Erro no download: ' + err.message);
        }
    },

    async downloadZip() {
        try {
            Toast.info('Gerando ZIP... isso pode levar um momento.');
            const blob = await API.downloadBlob('/api/section/outputs.zip');
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'outputs.zip';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (err) {
            Toast.error('Erro ao baixar ZIP: ' + err.message);
        }
    },

    formatSize(bytes) {
        if (!bytes) return '';
        const units = ['B', 'KB', 'MB', 'GB'];
        let i = 0;
        let size = bytes;
        while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
        return `${size.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};
