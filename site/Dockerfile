# site/Dockerfile — serves the static KrishiVaani frontend via nginx
# Railway will auto-detect this Dockerfile when the root directory is set to /site.
FROM nginx:1.25-alpine

# Remove default nginx page
RUN rm -rf /usr/share/nginx/html/*

# Copy static site files
COPY . /usr/share/nginx/html/

# Nginx config: serve index.html for all routes, gzip, correct MIME types
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    gzip on;\n\
    gzip_types text/plain text/css application/javascript image/svg+xml;\n\
    gzip_min_length 256;\n\
    add_header X-Frame-Options SAMEORIGIN;\n\
    add_header X-Content-Type-Options nosniff;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
    location ~* \\.(css|js|svg|png|jpg|woff2|ico)$ {\n\
        expires 7d;\n\
        add_header Cache-Control "public, immutable";\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
