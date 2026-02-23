/**
 * Dashboard — navegação entre painéis, load inicial, utils
 */
const Dashboard = {
    currentPanel: 'home',
    user: null,
    pollInterval: null,

    async init() {
        try {
            this.user = await Auth.getMe();
            document.getElementById('user-email').textContent = this.user.email;
            document.getElementById('user-role').textContent = this.user.role === 'MASTER' ? 'Administrador' : 'Usuário';

            // Show invites panel for MASTER
            if (this.user.role === 'MASTER') {
                const navInvites = document.getElementById('nav-invites');
                navInvites.style.display = '';
                navInvites.onclick = () => Dashboard.navigate('invites');
            }

            this.navigate('home');
        } catch (err) {
            Auth.logout();
        }
    },

    navigate(panel) {
        // Stop any polling
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }

        // Hide all panels
        document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));

        // Show target panel
        const target = document.getElementById(`panel-${panel}`);
        if (target) target.classList.remove('hidden');

        // Update sidebar active state
        document.querySelectorAll('.sidebar-item').forEach(item => {
            item.classList.toggle('active', item.dataset.panel === panel);
        });

        this.currentPanel = panel;

        // Close mobile sidebar
        this.closeSidebar();

        // Load panel data
        switch (panel) {
            case 'home': this.loadHome(); break;
            case 'projects': Projects.load(); break;
            case 'project-detail': ProjectDetail.load(); break;
            case 'jobs': Jobs.load(); break;
            case 'downloads': Downloads.load(); break;
            case 'invites': Invites.load(); break;
        }
    },

    async loadHome() {
        try {
            const [projects, jobs] = await Promise.all([
                API.get('/api/projects'),
                API.get('/api/jobs'),
            ]);

            document.getElementById('home-project-count').textContent = projects.length;

            const activeJobs = jobs.filter(j => j.status === 'queued' || j.status === 'running');
            document.getElementById('home-job-count').textContent = activeJobs.length;

            // Recent jobs
            const container = document.getElementById('home-recent-jobs');
            if (jobs.length === 0) {
                container.innerHTML = '<p class="text-gray-500 text-sm">Nenhum job ainda</p>';
            } else {
                container.innerHTML = jobs.slice(0, 5).map(job => `
                    <div class="flex items-center justify-between p-3 bg-gray-700/50 rounded-lg">
                        <div>
                            <span class="text-sm">${job.project_id.substring(0, 8)}...</span>
                            <span class="${this.statusBadgeClass(job.status)} ml-2">${this.statusLabel(job.status)}</span>
                        </div>
                        <div class="text-xs text-gray-500">${this.timeAgo(job.created_at)}</div>
                    </div>
                `).join('');
            }

            // Poll if active jobs
            if (activeJobs.length > 0) {
                this.pollInterval = setInterval(() => {
                    if (this.currentPanel === 'home') this.loadHome();
                }, 2500);
            }
        } catch (err) {
            console.error('Error loading home:', err);
        }
    },

    async renderAll() {
        if (!await this.confirm('Renderizar Tudo', 'Enviar todos os projetos da seção atual para renderização?')) return;
        try {
            const result = await API.post('/api/section/render_all');
            const count = Array.isArray(result) ? result.length : 0;
            Toast.success(`${count} processamento(s) criado(s)!`);
            this.navigate('jobs');
        } catch (err) {
            Toast.error(err.message);
        }
    },

    toggleSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        sidebar.classList.toggle('-translate-x-full');
        overlay.classList.toggle('hidden');
    },

    closeSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        if (!sidebar.classList.contains('-translate-x-full') && window.innerWidth < 768) {
            sidebar.classList.add('-translate-x-full');
            overlay.classList.add('hidden');
        }
    },

    // Confirm dialog
    confirm(title, message) {
        return new Promise((resolve) => {
            const dialog = document.getElementById('confirm-dialog');
            document.getElementById('confirm-title').textContent = title;
            document.getElementById('confirm-message').textContent = message;
            dialog.classList.remove('hidden');

            const okBtn = document.getElementById('confirm-ok');
            const cancelBtn = document.getElementById('confirm-cancel');

            const cleanup = () => {
                dialog.classList.add('hidden');
                okBtn.replaceWith(okBtn.cloneNode(true));
                cancelBtn.replaceWith(cancelBtn.cloneNode(true));
            };

            document.getElementById('confirm-ok').addEventListener('click', () => { cleanup(); resolve(true); });
            document.getElementById('confirm-cancel').addEventListener('click', () => { cleanup(); resolve(false); });
        });
    },

    // Utils
    statusBadgeClass(status) {
        const map = {
            'queued': 'badge badge-queued',
            'running': 'badge badge-running',
            'done': 'badge badge-done',
            'failed': 'badge badge-failed',
            'error': 'badge badge-failed',
        };
        return map[status] || 'badge';
    },

    statusLabel(status) {
        const map = {
            'queued': 'Na Fila',
            'running': 'Rodando',
            'done': 'Concluído',
            'failed': 'Erro',
            'error': 'Erro',
        };
        return map[status] || status;
    },

    timeAgo(dateStr) {
        const date = new Date(dateStr);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);
        if (seconds < 60) return 'agora';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}min atrás`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h atrás`;
        return date.toLocaleDateString('pt-BR');
    },

    formatDuration(ms) {
        if (!ms) return '—';
        const s = Math.floor(ms / 1000);
        const min = Math.floor(s / 60);
        const sec = s % 60;
        return `${min}:${String(sec).padStart(2, '0')}`;
    }
};

// Mobile menu
document.getElementById('mobile-menu-btn').addEventListener('click', () => Dashboard.toggleSidebar());

// Toast
const Toast = {
    show(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    },
    success(msg) { this.show(msg, 'success'); },
    error(msg) { this.show(msg, 'error'); },
    info(msg) { this.show(msg, 'info'); },
};
