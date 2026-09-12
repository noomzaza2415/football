/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Team crests come from the data provider's CDN.
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "crests.football-data.org" },
      { protocol: "https", hostname: "media.api-sports.io" },
    ],
  },
};

export default nextConfig;
