/** Admin step-up (IFORA-33): lets `http()` ask the signed-in administrator for a fresh second-factor code and retry. */

type Asker = () => Promise<void>;
let asker: Asker | null = null;

export function setStepUpAsker(fn: Asker | null) {
  asker = fn;
}

/** Resolves true once the administrator confirmed; false when nobody can ask (no dialog mounted) or they cancelled. */
export async function askStepUp(): Promise<boolean> {
  if (!asker) return false;
  try {
    await asker();
    return true;
  } catch {
    return false;
  }
}

export const STEPUP_REQUIRED = "stepup_required";
