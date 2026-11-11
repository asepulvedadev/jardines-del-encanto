export const SARA_AUDIO_LIMIT = 512 * 1024;
export const SARA_AUDIO_DURATION = 60000;
export function saraRecorderMime(
  supported: (mime: string) => boolean,
): string | null {
  return (
    [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4",
      "audio/webm",
      "audio/ogg",
    ].find(supported) ?? null
  );
}
export function saraAudioExtension(mime: string): string {
  return mime.startsWith("audio/ogg")
    ? "ogg"
    : mime.startsWith("audio/mp4")
      ? "mp4"
      : "webm";
}
/** Capture is local only; uploading/transcribing requires a separate user action. */
export class SaraRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private chunks: Blob[] = [];
  private size = 0;
  private discarded = false;
  private starting = false;
  constructor(
    private readonly onPreview: (file: File) => void,
    private readonly onError: (message: string) => void,
    private readonly onStopped: () => void,
  ) {}
  async start(): Promise<void> {
    if (this.starting || this.recorder)
      throw new Error("Ya hay una grabación en curso.");
    if (
      !globalThis.isSecureContext ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    )
      throw new Error(
        "La grabación no está disponible. Adjunta una nota de voz compatible.",
      );
    const mime = saraRecorderMime((value) =>
      MediaRecorder.isTypeSupported(value),
    );
    if (!mime)
      throw new Error(
        "Este navegador no tiene un formato de grabación compatible. Adjunta un audio.",
      );
    this.discarded = false;
    this.starting = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (this.discarded) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      this.stream = stream;
      this.chunks = [];
      this.size = 0;
      const recorder = new MediaRecorder(stream, { mimeType: mime });
      this.recorder = recorder;
      recorder.ondataavailable = (event) => {
        if (this.discarded || !event.data.size) return;
        this.size += event.data.size;
        if (this.size > SARA_AUDIO_LIMIT) {
          this.onError("La nota superó 512 KiB. Graba una nota más corta.");
          this.cancel();
          return;
        }
        this.chunks.push(event.data);
      };
      recorder.onerror = () => {
        this.onError(
          "No pudimos grabar la nota. Revisa el permiso del micrófono.",
        );
        this.cancel();
      };
      recorder.onstop = () => {
        const chunks = this.chunks;
        this.chunks = [];
        this.release();
        this.recorder = null;
        this.onStopped();
        if (this.discarded) return;
        const blob = new Blob(chunks, { type: mime });
        if (!blob.size) {
          this.onError("La grabación está vacía. Intenta de nuevo.");
          return;
        }
        this.onPreview(
          new File([blob], `nota-de-voz.${saraAudioExtension(mime)}`, {
            type: mime,
          }),
        );
      };
      recorder.start(250);
      this.timer = setTimeout(() => this.stop(), SARA_AUDIO_DURATION);
    } catch {
      this.release();
      this.recorder = null;
      this.onStopped();
      if (!this.discarded)
        throw new Error(
          "No pudimos usar el micrófono. Revisa el permiso o adjunta un audio.",
        );
    } finally {
      this.starting = false;
    }
  }
  stop() {
    if (this.recorder && this.recorder.state !== "inactive")
      this.recorder.stop();
    this.release();
  }
  cancel() {
    this.discarded = true;
    this.chunks = [];
    this.stop();
    this.onStopped();
  }
  private release() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.stream) for (const track of this.stream.getTracks()) track.stop();
    this.stream = null;
  }
  dispose() {
    this.cancel();
  }
}
