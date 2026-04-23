import { Sidebar } from "./sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen xl:grid xl:grid-cols-[280px_1fr]">
      <Sidebar />
      <main className="min-h-screen px-5 py-6 sm:px-8 lg:px-10">{children}</main>
    </div>
  );
}
