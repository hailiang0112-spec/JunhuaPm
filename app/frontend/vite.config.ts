import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { colorMixFallback } from "./colorMixFallback";

// 开发时 /api 代理到后端；保留浏览器的 Host 头，使 Django 的 CSRF 来源校验与页面同源
const api = `http://127.0.0.1:${process.env.API_PORT || 8000}`;
const web = Number(process.env.WEB_PORT || 5173);

export default defineConfig({
  plugins: [react(), colorMixFallback("src/styles/tokens.css")],
  build: { target: ["safari16", "chrome100"] },
  server: { port: web, strictPort: true, proxy: { "/api": { target: api, changeOrigin: false } } },
  preview: { port: 4173, proxy: { "/api": { target: api, changeOrigin: false } } },
});
