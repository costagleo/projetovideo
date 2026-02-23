/**
 * API — wrapper fetch para todos os endpoints
 */
const API = {
    /**
     * Faz uma requisição fetch autenticada.
     */
    async request(method, url, body = null, options = {}) {
        const headers = {};
        const token = localStorage.getItem('token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        const fetchOpts = { method, headers };

        if (body instanceof FormData) {
            fetchOpts.body = body;
        } else if (body !== null) {
            headers['Content-Type'] = 'application/json';
            fetchOpts.body = JSON.stringify(body);
        }

        const resp = await fetch(url, fetchOpts);

        if (resp.status === 401) {
            localStorage.removeItem('token');
            window.location.href = '/login';
            throw new Error('Sessão expirada');
        }

        if (!resp.ok) {
            let detail = `Erro ${resp.status}`;
            try {
                const data = await resp.json();
                detail = data.detail || detail;
            } catch {}
            throw new Error(detail);
        }

        // Some endpoints return empty body (204)
        if (resp.status === 204 || resp.headers.get('content-length') === '0') {
            return null;
        }

        // If expecting blob, return blob
        if (options.blob) {
            return resp.blob();
        }

        return resp.json();
    },

    get(url) { return this.request('GET', url); },
    post(url, body) { return this.request('POST', url, body); },
    patch(url, body) { return this.request('PATCH', url, body); },
    delete(url) { return this.request('DELETE', url); },

    /**
     * Upload de arquivo(s) com FormData
     */
    upload(url, formData) {
        return this.request('POST', url, formData);
    },

    /**
     * Download autenticado (retorna blob)
     */
    downloadBlob(url) {
        return this.request('GET', url, null, { blob: true });
    }
};
