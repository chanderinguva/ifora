"use client";

import { createContext } from "react";

/** Lets the pill tray insert into (or drop onto) whichever datapill field is on screen. Absent outside the studio. */
export type PillRegistry = {
  fields: Map<string, (path: string) => void>;
  active: { current: string | null };
};
export const PillFieldsContext = createContext<PillRegistry | null>(null);
