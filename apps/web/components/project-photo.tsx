import Image from "next/image";

type Props = {
  name: string;
  alt: string;
  className?: string;
  eager?: boolean;
  sizes?: string;
};

// Pre-encoded owner photographs avoid runtime cache writes in the read-only container.
export function ProjectPhoto({
  name,
  alt,
  className = "",
  eager = false,
  sizes = "100vw",
}: Props) {
  return (
    <picture>
      <source
        type="image/webp"
        srcSet={`/media/${name}-960.webp 960w, /media/${name}-1920.webp 1920w`}
        sizes={sizes}
      />
      <Image
        src={`/media/${name}-1920.webp`}
        alt={alt}
        width={1920}
        height={1080}
        unoptimized
        loading={eager ? "eager" : "lazy"}
        fetchPriority={eager ? "high" : "auto"}
        className={className}
      />
    </picture>
  );
}
