import type { ReactNode } from "react";

/** A titled panel. `as` keeps each page's existing heading level. */
export default function SectionCard({
  title, children, as: Heading = "h3",
}: { title: string; children: ReactNode; as?: "h2" | "h3" }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <Heading className="text-lg font-semibold text-slate-900">{title}</Heading>
      <div className="mt-4">{children}</div>
    </section>
  );
}
