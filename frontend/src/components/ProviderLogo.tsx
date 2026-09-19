/**
 * Original letter-mark badges, not publisher trademarks.
 *
 * Real logos are registered trademarks and cannot be redistributed inside an
 * open-source repository. These marks use each brand's general colour family so
 * the list stays scannable without copying protected artwork.
 */
type Brand = {
  mark: string;
  background: string;
  foreground: string;
};

const BRANDS: Record<string, Brand> = {
  elsevier: { mark: "EL", background: "#ff6d00", foreground: "#ffffff" },
  openalex: { mark: "OA", background: "#1f6feb", foreground: "#ffffff" },
  springer: { mark: "SN", background: "#0b7285", foreground: "#ffffff" },
  crossref: { mark: "CR", background: "#2f6f4f", foreground: "#ffffff" },
  arxiv: { mark: "AX", background: "#b31b1b", foreground: "#ffffff" },
  pubmed: { mark: "PM", background: "#22577a", foreground: "#ffffff" },
  unpaywall: { mark: "UP", background: "#7b2ff7", foreground: "#ffffff" },
  acs: { mark: "AC", background: "#0b5394", foreground: "#ffffff" },
  science: { mark: "SC", background: "#8a1c1c", foreground: "#ffffff" },
  wiley: { mark: "WI", background: "#0f5c8c", foreground: "#ffffff" },
};

function fallback(name: string): Brand {
  const mark = name.replace(/[^a-z]/gi, "").slice(0, 2).toUpperCase() || "??";
  return { mark, background: "#5b6b82", foreground: "#ffffff" };
}

export function ProviderLogo({ provider, size = 34 }: { provider: string; size?: number }) {
  const brand = BRANDS[provider.toLowerCase()] ?? fallback(provider);
  return (
    <span
      className="provider-logo"
      title={provider}
      aria-label={provider}
      style={{
        width: size,
        height: size,
        background: brand.background,
        color: brand.foreground,
        fontSize: size * 0.4,
      }}
    >
      {brand.mark}
    </span>
  );
}

export function knownBrands(): string[] {
  return Object.keys(BRANDS);
}
