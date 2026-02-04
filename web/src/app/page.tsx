import { redirect } from "next/navigation";

export default function HomePage() {
  // Single-user mode - redirect directly to research
  redirect("/research");
}
