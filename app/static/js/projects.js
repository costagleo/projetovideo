/**
 * Projects — lista, criação e exclusão de projetos
 */
const Projects = {
    list: [],

    async load() {
        try {
            this.list = await API.get('/api/projects');
            this.render();
        } catch (err) {
            Toast.error('Erro ao carregar projetos: ' + err.message);
        }
    },

    render() {
        const container = document.getElementById('projects-list');
        if (this.list.length === 0) {
            container.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                    </svg>
                    <p class="text-gray-500">Nenhum projeto ainda</p>
                    <button onclick="Projects.showCreateModal()" class="mt-3 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded-lg text-sm">
                        Criar Primeiro Projeto
                    </button>
                </div>
            `;
            return;
        }

        container.innerHTML = this.list.map(project => {
            const formatLabel = project.format === 'landscape' ? '16:9' : '9:16';
            const fitLabel = { smart_background: 'Smart BG', contain_pad: 'Contain', cover_crop: 'Cover' }[project.fit_mode] || project.fit_mode;
            return `
                <div class="bg-gray-800 rounded-lg p-5 hover:bg-gray-750 cursor-pointer transition-colors border border-gray-700 hover:border-indigo-500/30"
                     onclick="Projects.open('${project.id}')">
                    <div class="flex items-start justify-between mb-3">
                        <h3 class="font-semibold text-gray-100 truncate">${this.escapeHtml(project.name)}</h3>
                        <button onclick="event.stopPropagation(); Projects.remove('${project.id}')"
                            class="p-1 text-gray-500 hover:text-red-400 transition-colors" title="Excluir">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                            </svg>
                        </button>
                    </div>
                    <div class="flex gap-2 text-xs">
                        <span class="px-2 py-0.5 bg-gray-700 rounded text-gray-400">${formatLabel}</span>
                        <span class="px-2 py-0.5 bg-gray-700 rounded text-gray-400">${fitLabel}</span>
                        <span class="px-2 py-0.5 bg-gray-700 rounded text-gray-400">${project.fps}fps</span>
                    </div>
                    <p class="text-xs text-gray-500 mt-3">${new Date(project.created_at).toLocaleDateString('pt-BR')}</p>
                </div>
            `;
        }).join('');
    },

    open(projectId) {
        ProjectDetail.projectId = projectId;
        const navDetail = document.getElementById('nav-project-detail');
        navDetail.style.display = '';
        const project = this.list.find(p => p.id === projectId);
        if (project) {
            document.getElementById('nav-project-name').textContent = project.name;
        }
        Dashboard.navigate('project-detail');
    },

    async remove(projectId) {
        if (!await Dashboard.confirm('Excluir Projeto', 'Tem certeza que deseja excluir este projeto? Todos os arquivos serão removidos.')) return;
        try {
            await API.delete(`/api/projects/${projectId}`);
            Toast.success('Projeto excluído');
            this.load();
        } catch (err) {
            Toast.error(err.message);
        }
    },

    showCreateModal() {
        document.getElementById('create-project-modal').classList.remove('hidden');
        document.getElementById('proj-name').focus();
    },

    hideCreateModal() {
        document.getElementById('create-project-modal').classList.add('hidden');
        document.getElementById('create-project-form').reset();
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Create project form
document.getElementById('create-project-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        const project = await API.post('/api/projects', {
            name: document.getElementById('proj-name').value,
            format: document.getElementById('proj-format').value,
            fit_mode: document.getElementById('proj-fit-mode').value,
            fps: parseInt(document.getElementById('proj-fps').value),
            transition_s: parseFloat(document.getElementById('proj-transition').value),
            preset: document.getElementById('proj-preset').value,
        });
        Projects.hideCreateModal();
        Toast.success('Projeto criado!');
        Projects.open(project.id);
    } catch (err) {
        Toast.error(err.message);
    }
});
