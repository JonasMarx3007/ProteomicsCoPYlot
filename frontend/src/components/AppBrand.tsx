import { withBasePath } from "../lib/basePath";

type AppBrandProps = {
  title?: string;
  subtitle?: string;
  size?: "sm" | "md";
  align?: "left" | "center";
  className?: string;
};

export default function AppBrand({
  title = "Proteomics CoPYlot",
  subtitle,
  size = "md",
  align = "left",
  className = "",
}: AppBrandProps) {
  const iconSize = size === "sm" ? "h-9 w-9" : "h-11 w-11";
  const titleSize = size === "sm" ? "text-lg" : "text-xl";
  const subtitleSize = size === "sm" ? "text-xs" : "text-sm";

  return (
    <div
      className={[
        "flex min-w-0 items-center gap-3",
        align === "center" ? "justify-center text-center" : "text-left",
        className,
      ].join(" ")}
    >
      <img
        src={withBasePath("/favicon.ico")}
        alt=""
        aria-hidden="true"
        className={[
          iconSize,
          "shrink-0 rounded-xl object-contain shadow-sm ring-1 ring-slate-200",
        ].join(" ")}
      />
      <div className="min-w-0">
        <div className={[titleSize, "break-words font-bold leading-tight tracking-tight text-slate-900 [overflow-wrap:normal]"].join(" ")}>
          {title}
        </div>
        {subtitle ? (
          <div className={[subtitleSize, "mt-0.5 leading-snug text-slate-500"].join(" ")}>
            {subtitle}
          </div>
        ) : null}
        <a className="text-xs text-slate-500 underline" href={withBasePath("/licenses.html")} target="_blank" rel="noreferrer">Licences</a>
      </div>
    </div>
  );
}
