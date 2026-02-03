import { validateRequest } from "@/lib/auth";
import { redirect } from "next/navigation";
import { Navbar } from "@/components/Navbar";

export default async function ResearchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = await validateRequest();

  if (!user) {
    redirect("/auth/login");
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Navbar username={user.username} />
      <main className="container mx-auto px-4 py-6">{children}</main>
    </div>
  );
}
