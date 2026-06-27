/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output traces only the files the server actually needs, so the
  // production image and its runtime memory footprint stay small — important on
  // a 1 GB Raspberry Pi. `node server.js` then serves the app.
  output: "standalone",
  experimental: {
    serverActions: { allowedOrigins: ["localhost:3000"] },
  },
};
module.exports = nextConfig;
