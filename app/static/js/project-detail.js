/**
 * ProjectDetail — upload áudio/imagens, reorder, render individual
 */
const ProjectDetail = {
    projectId: null,
    project: null,
    track: null,
    images: [],

    async load() {
        if (!this.projectId) {
            Dashboard.navigate('projects');
            return;
        }

        try {
            this.project = await API.get(`/api/projects/${this.projectId}`);
            this.track = this.project.tracks && this.project.tracks.length > 0 ? this.project.tracks[0] : null;

            // Header
            document.getElementById('detail-project-name').textContent = this.project.name;
            document.getElementById('detail-project-format').textContent = this.project.format === 'landscape' ? '16:9' : '9:16';

            // Info
            const fitLabels = { smart_background: 'Smart Background', contain_pad: 'Contain (Pad)', cover_crop: 'Cover (Crop)' };
            document.getElementById('detail-project-info').innerHTML = `
                <div class="grid grid-cols-2 gap-2">
                    <p><span class="text-gray-500">Formato:</span> ${this.project.format === 'landscape' ? 'Landscape 16:9' : 'Vertical 9:16'}</p>
                    <p><span class="text-gray-500">Fit Mode:</span> ${fitLabels[this.project.fit_mode] || this.project.fit_mode}</p>
                    <p><span class="text-gray-500">FPS:</span> ${this.project.fps}</p>
                    <p><span class="text-gray-500">Transição:</span> ${this.project.transition_s}s</p>
                    <p><span class="text-gray-500">Preset:</span> ${this.project.preset}</p>
                </div>
            `;

            // Audio info
            if (this.track && this.track.audio_path) {
                const duration = Dashboard.formatDuration(this.track.duration_ms);
                document.getElementById('detail-audio-info').innerHTML = `
                    <div class="flex items-center gap-2">
                        <svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                        </svg>
                        <span class="text-green-400">Áudio enviado</span>
                        <span class="text-gray-500">(${duration})</span>
                    </div>
                `;
            } else {
                document.getElementById('detail-audio-info').innerHTML = '<span class="text-gray-500">Nenhum áudio enviado</span>';
            }

            // Load images
            if (this.track) {
                await this.loadImages();
            }

        } catch (err) {
            Toast.error('Erro ao carregar projeto: ' + err.message);
        }

        this.setupDropZones();
    },

    async loadImages() {
        if (!this.track) return;
        // Images are embedded in the track from the project detail response
        this.images = (this.track.images || []).sort((a, b) => a.order_index - b.order_index);
        this.renderImages();
    },

    renderImages() {
        const grid = document.getElementById('images-grid');
        const images = this.images;
        document.getElementById('detail-image-count').textContent = `${images.length} imagen${images.length !== 1 ? 's' : ''}`;

        if (images.length === 0) {
            grid.innerHTML = '';
            return;
        }

        grid.innerHTML = images.map((img, idx) => `
            <div class="image-thumb" draggable="true" data-id="${img.id}" data-index="${idx}">
                <img src="/api/outputs/${this.projectId}/${encodeURIComponent(img.path.split('/').pop())}/download" alt="Imagem ${idx + 1}"
                     onerror="this.parentElement.style.background='#374151'; this.style.display='none'">
                <span class="order-badge">${idx + 1}</span>
                <span class="delete-btn" onclick="event.stopPropagation(); ProjectDetail.deleteImage('${img.id}')">&times;</span>
            </div>
        `).join('');

        this.setupDragDrop();
    },

    setupDropZones() {
        // Audio drop zone
        const audioDrop = document.getElementById('audio-drop-zone');
        const audioInput = document.getElementById('audio-input');

        audioDrop.onclick = () => audioInput.click();
        audioDrop.ondragover = (e) => { e.preventDefault(); audioDrop.classList.add('dragover'); };
        audioDrop.ondragleave = () => audioDrop.classList.remove('dragover');
        audioDrop.ondrop = (e) => {
            e.preventDefault();
            audioDrop.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) this.uploadAudio(e.dataTransfer.files[0]);
        };
        audioInput.onchange = () => {
            if (audioInput.files.length > 0) this.uploadAudio(audioInput.files[0]);
        };

        // Images drop zone
        const imagesDrop = document.getElementById('images-drop-zone');
        const imagesInput = document.getElementById('images-input');

        imagesDrop.onclick = () => imagesInput.click();
        imagesDrop.ondragover = (e) => { e.preventDefault(); imagesDrop.classList.add('dragover'); };
        imagesDrop.ondragleave = () => imagesDrop.classList.remove('dragover');
        imagesDrop.ondrop = (e) => {
            e.preventDefault();
            imagesDrop.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) this.uploadImages(e.dataTransfer.files);
        };
        imagesInput.onchange = () => {
            if (imagesInput.files.length > 0) this.uploadImages(imagesInput.files);
        };
    },

    async uploadAudio(file) {
        if (!this.track) {
            Toast.error('Track não encontrada. Recarregue o projeto.');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            Toast.info('Enviando áudio...');
            await API.upload(`/api/tracks/${this.track.id}/audio`, formData);
            Toast.success('Áudio enviado com sucesso!');
            this.load(); // Reload to get updated duration
        } catch (err) {
            Toast.error('Erro no upload: ' + err.message);
        }
    },

    async uploadImages(files) {
        if (!this.track) {
            Toast.error('Track não encontrada. Recarregue o projeto.');
            return;
        }

        const formData = new FormData();
        for (const file of files) {
            formData.append('files', file);
        }

        try {
            Toast.info(`Enviando ${files.length} imagen(s)...`);
            const newImages = await API.upload(`/api/tracks/${this.track.id}/images`, formData);
            // Merge new images with existing
            this.images = [...this.images, ...newImages].sort((a, b) => a.order_index - b.order_index);
            this.renderImages();
            Toast.success(`${files.length} imagen(s) enviada(s)!`);
        } catch (err) {
            Toast.error('Erro no upload: ' + err.message);
        }
    },

    setupDragDrop() {
        const thumbs = document.querySelectorAll('.image-thumb');
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

            thumb.addEventListener('dragend', () => {
                thumb.classList.remove('dragging');
            });

            thumb.addEventListener('drop', async (e) => {
                e.preventDefault();
                if (dragSrc === thumb) return;

                const grid = document.getElementById('images-grid');
                const allThumbs = [...grid.children];
                const fromIndex = allThumbs.indexOf(dragSrc);
                const toIndex = allThumbs.indexOf(thumb);

                // Reorder in DOM
                if (fromIndex < toIndex) {
                    thumb.after(dragSrc);
                } else {
                    thumb.before(dragSrc);
                }

                // Build new order
                const reordered = [...grid.children].map((el, idx) => ({
                    image_id: el.dataset.id,
                    order_index: idx,
                }));

                // Update local array
                const newImages = reordered.map(r => this.images.find(img => img.id === r.image_id)).filter(Boolean);
                this.images = newImages;

                // Update badges
                [...grid.children].forEach((el, idx) => {
                    const badge = el.querySelector('.order-badge');
                    if (badge) badge.textContent = idx + 1;
                });

                // Send to API
                try {
                    await API.patch('/api/images/reorder', { images: reordered });
                } catch (err) {
                    Toast.error('Erro ao reordenar: ' + err.message);
                }
            });
        });
    },

    async deleteImage(imageId) {
        // Remove from local list and re-render
        this.images = this.images.filter(img => img.id !== imageId);
        this.renderImages();
        // TODO: Add API endpoint for single image deletion if needed
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
