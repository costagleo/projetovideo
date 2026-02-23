/**
 * Invites — painel MASTER: criar/listar/excluir convites
 */
const Invites = {
    list: [],

    async load() {
        try {
            this.list = await API.get('/api/invites');
            this.render();
        } catch (err) {
            Toast.error('Erro ao carregar convites: ' + err.message);
        }
    },

    render() {
        const container = document.getElementById('invites-list');

        if (this.list.length === 0) {
            container.innerHTML = `
                <div class="text-center py-12">
                    <svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
                    </svg>
                    <p class="text-gray-500">Nenhum convite criado</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.list.map(invite => {
            const isUsed = invite.used_at !== null;
            const isExpired = new Date(invite.expires_at) < new Date();
            let statusText, statusClass;

            if (isUsed) {
                statusText = 'Utilizado';
                statusClass = 'badge badge-done';
            } else if (isExpired) {
                statusText = 'Expirado';
                statusClass = 'badge badge-failed';
            } else {
                statusText = 'Pendente';
                statusClass = 'badge badge-queued';
            }

            return `
                <div class="bg-gray-800 rounded-lg p-4 border border-gray-700 flex items-center justify-between">
                    <div>
                        <div class="flex items-center gap-2 mb-1">
                            <span class="font-medium">${this.escapeHtml(invite.email)}</span>
                            <span class="${statusClass}">${statusText}</span>
                        </div>
                        <p class="text-xs text-gray-500">
                            Criado em ${new Date(invite.created_at).toLocaleDateString('pt-BR')}
                            &mdash; Expira em ${new Date(invite.expires_at).toLocaleDateString('pt-BR')}
                        </p>
                        ${invite.invite_url ? `
                        <div class="mt-2 flex items-center gap-2">
                            <input type="text" readonly value="${invite.invite_url}"
                                class="text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1 text-gray-400 w-80 max-w-full"
                                id="invite-url-${invite.id}">
                            <button onclick="Invites.copyUrl('${invite.id}')" class="text-xs text-indigo-400 hover:text-indigo-300">
                                Copiar
                            </button>
                        </div>
                        ` : ''}
                    </div>
                    <button onclick="Invites.remove('${invite.id}')"
                        class="p-2 text-gray-500 hover:text-red-400 transition-colors" title="Excluir">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                        </svg>
                    </button>
                </div>
            `;
        }).join('');
    },

    async remove(inviteId) {
        if (!await Dashboard.confirm('Excluir Convite', 'Tem certeza que deseja excluir este convite?')) return;
        try {
            await API.delete(`/api/invites/${inviteId}`);
            Toast.success('Convite excluído');
            this.load();
        } catch (err) {
            Toast.error(err.message);
        }
    },

    showCreateModal() {
        document.getElementById('create-invite-modal').classList.remove('hidden');
        document.getElementById('invite-email').focus();
    },

    hideCreateModal() {
        document.getElementById('create-invite-modal').classList.add('hidden');
        document.getElementById('create-invite-form').reset();
    },

    copyUrl(inviteId) {
        const input = document.getElementById(`invite-url-${inviteId}`);
        if (input) {
            navigator.clipboard.writeText(input.value).then(() => {
                Toast.success('Link copiado!');
            }).catch(() => {
                input.select();
                document.execCommand('copy');
                Toast.success('Link copiado!');
            });
        }
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Create invite form
document.getElementById('create-invite-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
        const invite = await API.post('/api/invites', {
            email: document.getElementById('invite-email').value,
        });
        Invites.hideCreateModal();
        Toast.success('Convite criado!');
        // Add to list with the invite_url from response
        Invites.list.unshift(invite);
        Invites.render();
    } catch (err) {
        Toast.error(err.message);
    }
});
