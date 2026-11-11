import type { Proposal } from "./settings-types";
export const SARA_FILE_LIMIT = 512 * 1024;
export type SaraStatus = {
  available: boolean;
  enabled: boolean;
  model: string | null;
  tools_count: number;
  voice_available: boolean;
};
export type SaraConversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};
export type SaraAttachment = {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
  kind: "document" | "audio";
  text: string;
  created_at: string;
};
export type SaraProposal = Proposal & { resolvable?: boolean };
export type SaraMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  state: "completed" | "pending" | "failed";
  attachments: SaraAttachment[];
  results: Record<string, unknown>[];
  proposals: SaraProposal[];
};
export type SaraSkill = {
  id: string;
  name: string;
  description: string;
  content: string;
  enabled: boolean;
  effective: boolean;
};
export type SaraTurnInput = {
  request_id: string;
  message: string;
  attachment_ids: string[];
};
export type SaraTurn = {
  user_message: SaraMessage;
  assistant_message: SaraMessage | null;
  state: "completed" | "pending" | "failed";
};
export type SaraDraft = { text: string; attachments: SaraAttachment[] };
export const EMPTY_SARA_DRAFT: SaraDraft = { text: "", attachments: [] };
export function mergeSaraConversations(
  current: SaraConversation[],
  incoming: SaraConversation[],
): SaraConversation[] {
  const records = new Map(current.map((value) => [value.id, value]));
  for (const value of incoming) {
    const known = records.get(value.id);
    if (!known || known.updated_at <= value.updated_at)
      records.set(value.id, value);
  }
  return [...records.values()].sort(
    (a, b) =>
      b.updated_at.localeCompare(a.updated_at) || b.id.localeCompare(a.id),
  );
}
export function mergeSaraMessages(
  current: SaraMessage[],
  incoming: SaraMessage[],
): SaraMessage[] {
  const records = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) records.set(message.id, message);
  return [...records.values()].sort(
    (a, b) =>
      a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id),
  );
}
export function saraUploadMime(filename: string, mime: string): string {
  const extension = filename.toLowerCase().split(".").pop() ?? "";
  const byExtension: Record<string, string> = {
    txt: "text/plain",
    md: "text/markdown",
    csv: "text/csv",
    pdf: "application/pdf",
    webm: "audio/webm",
    ogg: "audio/ogg",
    mp3: "audio/mpeg",
    wav: "audio/wav",
    mp4: "audio/mp4",
    m4a: "audio/mp4",
  };
  const expected = byExtension[extension];
  if (!expected)
    throw new Error(
      "Formato no compatible. Usa TXT, MD, CSV, PDF o audio WebM, Ogg, MP3, WAV o MP4.",
    );
  const base = mime.toLowerCase().split(";")[0].trim();
  const normalized =
    base === "audio/mp3"
      ? "audio/mpeg"
      : base === "audio/x-wav"
        ? "audio/wav"
        : base;
  if (
    normalized &&
    normalized !== expected &&
    !(extension === "md" && normalized === "text/plain")
  )
    throw new Error("El tipo del archivo no coincide con su extensión.");
  return expected;
}
export async function saraFileBase64(file: Blob): Promise<string> {
  if (!file.size || file.size > SARA_FILE_LIMIT)
    throw new Error("El archivo debe pesar entre 1 byte y 512 KiB.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 32768)
    binary += String.fromCharCode(...bytes.subarray(index, index + 32768));
  return btoa(binary);
}
export function saraProposalAvailable(proposal: SaraProposal): boolean {
  return proposal.resolvable !== false;
}

export type SaraSkillQuery = { start: number; end: number; query: string };
export function saraSkillQuery(
  text: string,
  caret: number,
): SaraSkillQuery | null {
  if (caret < 0 || caret > text.length) return null;
  const match = /(?:^|\s)\$([^\s$\[\]]*)$/.exec(text.slice(0, caret));
  return match
    ? { start: caret - match[1].length - 1, end: caret, query: match[1] }
    : null;
}
export function saraInsertSkill(
  text: string,
  token: SaraSkillQuery,
  name: string,
) {
  const mention = `$[${name.replace(/[\[\]\r\n]/g, " ")}] `;
  return {
    text: text.slice(0, token.start) + mention + text.slice(token.end),
    caret: token.start + mention.length,
  };
}
