"use client";

import { PageHeader } from "@/components/bits";
import { AppTiles } from "@/components/app-tiles";

export default function MyApps() {
  return (
    <div className="max-w-5xl">
      <PageHeader title="My apps" />
      <AppTiles />
    </div>
  );
}
