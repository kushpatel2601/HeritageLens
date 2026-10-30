import { ArchiveTabs } from "@/components/archive/archive-tabs";

export default function ArchiveLayout({ children }: LayoutProps<"/archive">) {
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <header className="mb-6">
        <p className="eyebrow mb-1">Archive</p>
        <h1 className="text-3xl font-semibold sm:text-4xl">The collection, and the machinery behind it</h1>
      </header>
      <ArchiveTabs />
      <div className="pt-6">{children}</div>
    </div>
  );
}
