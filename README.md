# telangana-farmer-whatsapp

An open-wa Easy API project with the Neo dashboard.

## Start

Use Node.js 22.21.1 or newer. Dependencies are installed by the initializer.

Copy .env.example to .env and fill in the values for your selected integrations.

```bash
npm start
```

Link WhatsApp using the QR code. Stop with Ctrl+C.

Open http://127.0.0.1:8080/dashboard/ for Neo and http://127.0.0.1:8080/api-docs/ for the HTTP API.

## Configuration

Edit wa.config.js. Easy API discovers this file automatically.

The browser choice is auto. Browser downloads and selected plugins are installed only when needed at startup and reused later.

Local .env files, dependency folders and session data are ignored by Git.

[Setup guide](https://openwa.dev/docs/getting-started/initializer) · [Configure a project](https://openwa.dev/new)
