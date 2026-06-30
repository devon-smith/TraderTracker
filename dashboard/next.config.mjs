/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a self-contained server bundle for the slim production Docker image.
  output: "standalone",
};

export default nextConfig;
