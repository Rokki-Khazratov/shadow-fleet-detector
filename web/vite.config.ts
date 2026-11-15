import {defineConfig} from 'vite';
export default defineConfig({server:{host:'127.0.0.1',proxy:{'/v1':process.env.SFD_API_PROXY ?? 'http://127.0.0.1:8000'}}});
