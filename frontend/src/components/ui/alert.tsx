"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { AlertTriangle, CheckCircle, Info, XCircle } from "lucide-react";

const alertVariants = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm [&>svg]:absolute [&>svg]:right-4 [&>svg]:top-4 [&>svg]:text-foreground [&>svg~div]:pointer-events-none [&>svg~div]:absolute [&>svg~div]:inset-0 [&>svg~div]:w-max [&>svg~div]:gap-2 [&>svg~div]:flex [&>svg~div]:items-center [&>svg~div]:rounded-lg [&>svg~div]:bg-muted [&>svg~div]:text-sm [&>svg~div]:dark:text-muted-foreground",
  {
    variants: {
      variant: {
        default: "bg-background text-foreground",
        destructive:
          "border-destructive/50 text-destructive dark:border-destructive [&>svg]:text-destructive",
        success:
          "border-green-500/50 text-green-700 dark:text-green-400 [&>svg]:text-green-500",
        warning:
          "border-amber-500/50 text-amber-700 dark:text-amber-400 [&>svg]:text-amaran",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  icon?: React.ReactNode;
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant, icon, ...props }, ref) => (
    <div
      ref={ref}
      role="alert"
      aria-live="polite"
      aria-atomic="true"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    >
      {icon}
      <div className="pointer-events-none absolute inset-0 flex items-center w-max gap-2 rounded-lg px-4 py-3 bg-muted text-sm dark:text-muted-foreground">
        {props.children}
      </div>
    </div>
  ),
);
Alert.displayName = "Alert";

const AlertTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <h5
    ref={ref}
    className={cn("mb-1 font-normal leading-none", className)}
    {...props}
  />
));
AlertTitle.displayName = "AlertTitle";

const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm font-medium [&>p]:leading-normal", className)}
    {...props}
  />
));
AlertDescription.displayName = "AlertDescription";

export { Alert, AlertTitle, AlertDescription, alertVariants };