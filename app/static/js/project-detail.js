/**
 * ProjectDetail — multi-track: áudio+imagens por trilha, reorder, render
 */
const ProjectDetail = {
    projectId: null,
    project: null,
    tracks: [],

    FIT_LABELS: {
        smart_background: 'Fundo Inteligente',
        contain_pad: 'Ajustar (com barras)',
        cover_crop: 'Preencher (com corte)',
    },

    async load() {
        if (!this.projectId) {
            Dashboard.navigate('projects');
            return;
        }

        try {
            this.project = await API.get(`/api/projects/${this.projectId}`);
            this.tracks = (this.project.tracks || []).sort((a, b) => a.order_index - b.order_index);

            // Header
            const nameEl = document.getElementById('detail-project-name');
            const formatEl = document.getElementById('detail-project-format');
            const infoEl = document.getElementById('detail-project-info');

            if (nameEl) nameEl.textContent = this.project.name;
            if (formatEl) formatEl.textContent = this.project.format === 'landscape' ? '16:9' : '9:16';

            // Info
            if (infoEl) {
                infoEl.innerHTML = `
                    <div class="grid grid-cols-2 gap-2">
                        <p><span class="text-gray-500">Formato:</span> ${this.project.format === 'landscape' ? 'Landscape 16:9' : 'Vertical 9:16'}</p>
                        <p><span class="text-gray-500">Ajuste:</span> ${this.FIT_LABELS[this.project.fit_mode] || this.project.fit_mode}</p>
                        <p><span class="text-gray-500">FPS:</span> ${this.project.fps}</p>
                        <p><span class="text-gray-500">Transição:</span> ${this.project.transition_s}s</p>
                        <p><span class="text-gray-500">Preset:</span> ${this.project.preset}</p>
                        <p><span class="text-gray-500">Trilhas:</span> ${this.tracks.length}</p>
                    </div>
                `;
            }

            this.renderTracks();

        } catch (err) {
            Toast.error('Erro ao carregar projeto: ' + err.message);
        }
    },

    renderTracks() {
        const container = document.getElementById('tracks-container');
        if (!container) return;

        container.innerHTML = this.tracks.map((track, tIdx) => {
            const images = (track.images || []).sort((a, b) => a.order_index - b.order_index);
            const hasAudio = !!track.audio_path;
            const duration = Dashboard.formatDuration(track.duration_ms);
            const trackNum = tIdx + 1;
            const canDelete = this.tracks.length > 1;

            return `
                <div class="bg-gray-800 rounded-lg p-4 md:p-5 border border-gray-700" data-track-id="${track.id}">
                    <!-- Track header -->
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center gap-2">
                            <div class="w-8 h-8 bg-indigo-600/30 rounded-full flex items-center justify-center text-indigo-400 text-sm font-bold">${trackNum}</div>
                            <h3 class="font-semibold">Trilha ${trackNum}</h3>
                        </div>
                        ${canDelete ? `
                        <button onclick="ProjectDetail.deleteTrack('${track.id}')" class="p-1.5 text-gray-500 hover:text-red-400 transition-colors" title="Remover trilha">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                            </svg>
                        </button>` : ''}
                    </div>

                    <!-- Audio section -->
                    <div class="mb-4">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-sm text-gray-400">Áudio</span>
                            ${hasAudio ? `<span class="text-xs text-green-400">${duration}</span>` : ''}
                        </div>
                        ${hasAudio ? `
                        <div class="flex items-center gap-2 p-3 bg-gray-700/50 rounded-lg">
                            <svg class="w-5 h-5 text-green-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                            </svg>
                            <span class="text-sm text-green-400 truncate">Áudio enviado</span>
                            <button onclick="document.getElementById('audio-input-${track.id}').click()" class="ml-auto text-xs text-indigo-400 hover:text-indigo-300 flex-shrink-0">Substituir</button>
                        </div>
                        ` : `
                        <div class="drop-zone" id="audio-zone-${track.id}" onclick="document.getElementById('audio-input-${track.id}').click()">
                            <svg class="w-8 h-8 mx-auto mb-1 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"/>
                            </svg>
                            <p class="text-gray-400 text-xs">Arraste ou <span class="text-indigo-400">selecione</span> o áudio</p>
                        </div>
                        `}
                        <input type="file" id="audio-input-${track.id}" accept="audio/*" class="hidden" onchange="ProjectDetail.uploadAudio('${track.id}', this.files[0])">
                    </div>

                    <!-- Images section -->
                    <div>
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-sm text-gray-400">Imagens</span>
                            <span class="text-xs text-gray-500">${images.length} imagen${images.length !== 1 ? 's' : ''}</span>
                        </div>
                        <div class="drop-zone mb-3" id="images-zone-${track.id}" onclick="document.getElementById('images-input-${track.id}').click()">
                            <svg class="w-8 h-8 mx-auto mb-1 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                            </svg>
                            <p class="text-gray-400 text-xs">Arraste ou <span class="text-indigo-400">selecione</span> imagens</p>
                        </div>
                        <input type="file" id="images-input-${track.id}" accept="image/*" multiple class="hidden" onchange="ProjectDetail.uploadImages('${track.id}', this.files)">
                        <div class="image-grid" id="images-grid-${track.id}">
                            ${images.map((img, idx) => `
                                <div class="image-thumb" draggable="true" data-id="${img.id}" data-track="${track.id}" data-index="${idx}">
                                    <div class="w-full h-full bg-gray-700 flex items-center justify-center text-gray-500 text-xs">IMG</div>
                                    <span class="order-badge">${idx + 1}</span>
                                    <span class="delete-btn" onclick="event.stopPropagation(); ProjectDetail.removeImage('${track.id}', '${img.id}')">&times;</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Setup drag-drop for all zones
        this.setupAllDropZones();
        this.setupAllDragDrop();
    },

    setupAllDropZones() {
        this.tracks.forEach(track => {
            // Audio drop zone
            const audioZone = document.getElementById(`audio-zone-${track.id}`);
            if (audioZone) {
                audioZone.ondragover = (e) => { e.preventDefault(); audioZone.classList.add('dragover'); };
                audioZone.ondragleave = () => audioZone.classList.remove('dragover');
                audioZone.ondrop = (e) => {
                    e.preventDefault();
                    audioZone.classList.remove('dragover');
                    const files = e.dataTransfer.files;
                    if (files.length > 0) this.uploadAudio(track.id, files[0]);
                };
            }

            // Images drop zone
            const imagesZone = document.getElementById(`images-zone-${track.id}`);
            if (imagesZone) {
                imagesZone.ondragover = (e) => { e.preventDefault(); imagesZone.classList.add('dragover'); };
                imagesZone.ondragleave = () => imagesZone.classList.remove('dragover');
                imagesZone.ondrop = (e) => {
                    e.preventDefault();
                    imagesZone.classList.remove('dragover');
                    const files = e.dataTransfer.files;
                    if (files.length > 0) this.uploadImages(track.id, files);
                };
            }
        });
    },

    setupAllDragDrop() {
        this.tracks.forEach(track => {
            const grid = document.getElementById(`images-grid-${track.id}`);
            if (!grid) return;
            const thumbs = grid.querySelectorAll('.image-thumb');
            let dragSrc = null;

            thumbs.forEach(thumb => {
                thumb.addEventListener('dragstart', (e) => {
                    dragSrc = thumb;
                    thumb.classList.add('dragging');
                    e.dataTransfer.effectAllowed = 'move';
                });
                thumb.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                });
                thumb.addEventListener('dragend', () => thumb.classList.remove('dragging'));
                thumb.addEventListener('drop', async (e) => {
                    e.preventDefault();
                    if (dragSrc === thumb || dragSrc.dataset.track !== thumb.dataset.track) return;
                    const fromIndex = [...grid.children].indexOf(dragSrc);
                    const toIndex = [...grid.children].indexOf(thumb);
                    if (fromIndex < toIndex) thumb.after(dragSrc); else thumb.before(dragSrc);

                    const reordered = [...grid.children].map((el, idx) => ({
                        image_id: el.dataset.id,
                        order_index: idx,
                    }));

                    [...grid.children].forEach((el, idx) => {
                        const badge = el.querySelector('.order-badge');
                        if (badge) badge.textContent = idx + 1;
                    });

                    try {
                        await API.patch('/api/images/reorder', { images: reordered });
                    } catch (err) {
                        Toast.error('Erro ao reordenar: ' + err.message);
                    }
                });
            });
        });
    },

    async uploadAudio(trackId, file) {
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);

        try {
            Toast.info('Enviando áudio...');
            await API.upload(`/api/tracks/${trackId}/audio`, formData);
            Toast.success('Áudio enviado!');
            this.load();
        } catch (err) {
            Toast.error('Erro no upload: ' + err.message);
        }
    },

    async uploadImages(trackId, files) {
        if (!files || files.length === 0) return;
        const formData = new FormData();
        for (const file of files) {
            formData.append('files', file);
        }

        try {
            Toast.info(`Enviando ${files.length} imagen(s)...`);
            await API.upload(`/api/tracks/${trackId}/images`, formData);
            Toast.success(`${files.length} imagen(s) enviada(s)!`);
            this.load();
        } catch (err) {
            Toast.error('Erro no upload: ' + err.message);
        }
    },

    async removeImage(trackId, imageId) {
        try {
            await API.delete(`/api/images/${imageId}`);
        } catch (err) {
            Toast.error('Erro ao remover imagem: ' + err.message);
            return;
        }
        // Update local state and re-render
        const track = this.tracks.find(t => t.id === trackId);
        if (track) {
            track.images = (track.images || []).filter(img => img.id !== imageId);
            this.renderTracks();
        }
    },

    async addTrack() {
        try {
            await API.post(`/api/projects/${this.projectId}/tracks`);
            Toast.success('Nova trilha adicionada!');
            this.load();
        } catch (err) {
            Toast.error(err.message);
        }
    },

    async deleteTrack(trackId) {
        if (!await Dashboard.confirm('Remover Trilha', 'Tem certeza que deseja remover esta trilha e todos os seus arquivos?')) return;
        try {
            await API.delete(`/api/projects/${this.projectId}/tracks/${trackId}`);
            Toast.success('Trilha removida');
            this.load();
        } catch (err) {
            Toast.error(err.message);
        }
    },

    async render() {
        if (!this.projectId) return;
        try {
            await API.post(`/api/projects/${this.projectId}/render`);
            Toast.success('Job de renderização criado!');
            Dashboard.navigate('jobs');
        } catch (err) {
            Toast.error(err.message);
        }
    },

    async deleteProject() {
        if (!await Dashboard.confirm('Excluir Projeto', 'Tem certeza? Todos os arquivos serão removidos permanentemente.')) return;
        try {
            await API.delete(`/api/projects/${this.projectId}`);
            Toast.success('Projeto excluído');
            document.getElementById('nav-project-detail').style.display = 'none';
            Dashboard.navigate('projects');
        } catch (err) {
            Toast.error(err.message);
        }
    }
};
