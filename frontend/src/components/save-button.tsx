import * as React from "react";
import { Button, type ButtonProps } from "@/components/ui/button";

/** A save button that only exists while there is something to save (see `useDirty`). */
export function SaveButton({ dirty, children = "Save changes", ...props }: { dirty: boolean } & ButtonProps) {
  if (!dirty) return null;
  return <Button {...props}>{children}</Button>;
}
