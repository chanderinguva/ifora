/** Root layout for the Ifora frontend. */

import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { BrandingProvider } from "@/lib/branding";
import { deploymentTitle } from "@/lib/deployment-title";

const inter = localFont({
  src: "./fonts/inter.woff2",
  weight: "100 900",
  display: "swap",
  variable: "--font-inter",
});

const mono = localFont({
  src: "./fonts/jetbrains-mono.woff2",
  weight: "100 800",
  display: "swap",
  variable: "--font-mono",
});

const lora = localFont({
  src: "./fonts/lora.woff2",
  weight: "400 700",
  display: "swap",
  variable: "--font-lora",
});

export const metadata: Metadata = {
  title: {
    default: deploymentTitle(process.env.NEXT_PUBLIC_APP_ENVIRONMENT),
    template: `%s | ${deploymentTitle(process.env.NEXT_PUBLIC_APP_ENVIRONMENT)}`,
  },
  description: "Identity, secure access and automation in one platform.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F8FAFC" },
    { media: "(prefers-color-scheme: dark)", color: "#0B1220" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${lora.variable} ${mono.variable}`} suppressHydrationWarning>
      <body className="font-sans antialiased" suppressHydrationWarning>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <BrandingProvider>{children}</BrandingProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

