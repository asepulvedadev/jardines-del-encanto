export const socialPlatforms = [
  ["facebook", "Facebook", "FB", "Páginas y presencia de la marca."],
  ["instagram", "Instagram", "IG", "Cuenta profesional y contenido visual."],
  ["tiktok", "TikTok", "TK", "Publicación sujeta a la aprobación de TikTok."],
  ["whatsapp", "WhatsApp", "WA", "Cuenta comercial y recepción de eventos."],
  ["telegram", "Telegram", "TG", "Vinculación mediante un código temporal."],
] as const;
export type SocialPlatform = (typeof socialPlatforms)[number][0];
export type SocialSettings = {
  configured: boolean;
  profile: { id: string; name: string } | null;
  last_sync: string | null;
  connections: {
    id: string;
    platform: string;
    username: string | null;
    display_name: string | null;
    status: string;
    connected_at?: string | null;
  }[];
  events: {
    id: string;
    event: string;
    platform: string | null;
    received_at: string;
    status: string;
  }[];
  limitations: { telegram: string; tiktok: string };
  webhook: { configured: boolean; path: string };
  hermes: { connected: false; mode: "manual" };
  sync_warning: string | null;
};
export type SocialIntent = {
  intent_id: string;
  auth_url: string | null;
  code: string | null;
  expires_at: string;
  instructions: string | null;
  platform: SocialPlatform | null;
};
export type SocialCompletion = {
  status: "connected" | "pending";
  settings?: SocialSettings;
};
