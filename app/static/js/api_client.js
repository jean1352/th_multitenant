/**
 * Cliente API Moderno con Gestión de Tokens JWT
 * - Almacena token en sessionStorage
 * - Inyecta Authorization header automáticamente
 * - Refresca el token en background antes de que expire
 */

class TokenManager {
    static TOKEN_KEY = 'auth_token';
    static EXPIRY_KEY = 'auth_expiry'; // Timestamp en milisegundos

    static setToken(token, expiresInSeconds) {
        const expiryTime = Date.now() + (expiresInSeconds * 1000);
        sessionStorage.setItem(this.TOKEN_KEY, token);
        sessionStorage.setItem(this.EXPIRY_KEY, expiryTime.toString());
    }

    static getToken() {
        return sessionStorage.getItem(this.TOKEN_KEY);
    }

    static clear() {
        sessionStorage.removeItem(this.TOKEN_KEY);
        sessionStorage.removeItem(this.EXPIRY_KEY);
    }

    static isExpiringSoon() {
        const expiry = sessionStorage.getItem(this.EXPIRY_KEY);
        if (!expiry) return true;
        
        const timeLeft = parseInt(expiry) - Date.now();
        // Consideramos "pronto" si faltan menos de 5 minutos (300000 ms)
        return timeLeft < 300000 && timeLeft > 0;
    }

    static isExpired() {
        const expiry = sessionStorage.getItem(this.EXPIRY_KEY);
        if (!expiry) return true;
        return Date.now() > parseInt(expiry);
    }
}

export class ApiClient {
    
    /**
     * Realiza el login y guarda el token.
     */
    static async login(email, password) {
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });

            const data = await this.handleResponse(response);
            
            // Guardar token y expiración
            if (data.access_token) {
                // Default 480 min si no viene del back
                const expires = data.expires_in || (480 * 60); 
                TokenManager.setToken(data.access_token, expires);
            }
            
            return data;
        } catch (error) {
            throw error;
        }
    }

    /**
     * Intenta refrescar el token silenciosamente.
     */
    static async refreshToken() {
        try {
            const token = TokenManager.getToken();
            if (!token) return false;

            console.log("🔄 Refrescando token en background...");
            
            const response = await fetch('/api/auth/refresh', {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.ok) {
                const data = await response.json();
                TokenManager.setToken(data.access_token, data.expires_in);
                console.log("✅ Token refrescado exitosamente.");
                return true;
            } else {
                console.warn("⚠️ Falló el refresco de token. Sesión podría expirar.");
                return false;
            }
        } catch (e) {
            console.error("Error refrescando token:", e);
            return false;
        }
    }

    /**
     * Método genérico para realizar peticiones autenticadas.
     */
    static async request(url, options = {}) {
        // 1. Verificar y Refrescar Token si es necesario
        if (TokenManager.getToken()) {
            if (TokenManager.isExpiringSoon()) {
                // No esperamos el await para no bloquear la UI, pero idealmente
                // deberíamos encadenar si el token ya expiró.
                // Si ya expiró, el request fallará con 401 y redirigirá.
                this.refreshToken(); 
            }
        }

        // 2. Preparar Headers
        const headers = options.headers || {};
        const token = TokenManager.getToken();
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        // Si no es FormData, asumimos JSON por defecto
        if (!(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
        } else {
            // Fetch maneja el Content-Type para FormData automáticamente (boundary)
            delete headers['Content-Type'];
        }

        options.headers = headers;

        // 3. Ejecutar Petición
        try {
            const response = await fetch(url, options);
            
            // 4. Manejo Global de Errores (401/403)
            if (response.status === 401) {
                // Token inválido o expirado -> Logout forzado
                TokenManager.clear();
                window.location.href = '/login';
                throw new Error('Sesión expirada. Por favor inicie sesión nuevamente.');
            }

            return await this.handleResponse(response);
        } catch (error) {
            console.error("API Error:", error);
            throw error;
        }
    }

    static async post(url, data) {
        const options = {
            method: 'POST',
            body: data instanceof FormData ? data : JSON.stringify(data)
        };
        return this.request(url, options);
    }

    static async put(url, data) {
        const options = {
            method: 'PUT',
            body: data instanceof FormData ? data : JSON.stringify(data)
        };
        return this.request(url, options);
    }

    static async get(url) {
        return this.request(url, { method: 'GET' });
    }

    static async delete(url) {
        // DELETE puede retornar 204 No Content
        const options = { method: 'DELETE' };
        
        // Copiamos lógica de request pero manejamos el 204 específicamente
        const token = TokenManager.getToken();
        const headers = { 'Authorization': `Bearer ${token}` };
        
        const response = await fetch(url, { method: 'DELETE', headers });
        
        if (response.status === 401) {
            TokenManager.clear();
            window.location.href = '/login';
            throw new Error('Sesión expirada.');
        }
        
        if (response.status === 204) return null;
        return await this.handleResponse(response);
    }

    static async handleResponse(response) {
        if (!response.ok) {
            let errorData;
            try {
                errorData = await response.json();
            } catch (e) {
                throw new Error(`Error HTTP ${response.status}`);
            }

            if (errorData.detail) {
                if (Array.isArray(errorData.detail)) {
                    const messages = errorData.detail.map(err => {
                        const field = err.loc[err.loc.length - 1]; 
                        return `• ${field}: ${err.msg}`;
                    });
                    throw new Error(messages.join('\n'));
                } else {
                    throw new Error(errorData.detail);
                }
            }
            throw new Error('Error desconocido en el servidor');
        }
        return await response.json();
    }
}

export function showToast(message, type = 'success') {
    const existingToasts = document.querySelectorAll('.custom-toast');
    existingToasts.forEach(t => t.remove());

    const toast = document.createElement('div');
    const color = type === 'error' ? 'bg-red-600' : 'bg-green-600';
    
    toast.className = `custom-toast fixed top-5 right-5 ${color} text-white px-6 py-4 rounded-lg shadow-xl transition-all duration-500 z-50 max-w-md whitespace-pre-wrap font-medium text-sm border-l-4 border-white/30`;
    
    toast.innerText = message;
    document.body.appendChild(toast);
    
    requestAnimationFrame(() => {
        toast.style.transform = 'translateY(10px)';
        toast.style.opacity = '1';
    });
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-20px)';
        setTimeout(() => toast.remove(), 500);
    }, 5000);
}