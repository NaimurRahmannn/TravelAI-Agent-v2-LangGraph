import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Travel AI Agent",
  description: "A LangGraph-powered travel planning workspace.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
