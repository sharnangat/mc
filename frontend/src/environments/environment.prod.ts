export const environment = {
  production: true,
  // Same-origin path; nginx reverse-proxies /mc/api/ to the backend (see /root/deploy/nginx/nginx-all.conf).
  apiBaseUrl: '/mc/api',
};
