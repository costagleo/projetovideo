/**
 * Auth — gerenciamento de token JWT e sessão
 */
const Auth = {
    getToken() {
        return localStorage.getItem('token');
    },

    setToken(token) {
        localStorage.setItem('token', token);
    },

    removeToken() {
        localStorage.removeItem('token');
    },

    async login(email, password) {
        const data = await API.post('/api/auth/login', { email, password });
        this.setToken(data.access_token);
        return data;
    },

    logout() {
        this.removeToken();
        window.location.href = '/login';
    },

    requireAuth() {
        if (!this.getToken()) {
            window.location.href = '/login';
        }
    },

    async getMe() {
        return API.get('/api/auth/me');
    }
};
