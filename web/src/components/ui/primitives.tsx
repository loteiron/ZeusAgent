import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends Omit<ComponentProps<"button">, "prefix"> {
  destructive?: boolean;
  ghost?: boolean;
  invert?: boolean;
  outlined?: boolean;
  prefix?: ReactNode;
  suffix?: ReactNode;
  size?: "default" | "icon" | "sm" | "xs" | null;
}

export function Button({
  className, destructive, ghost, invert, outlined, prefix, suffix,
  size = "default", children, type, ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      data-tone={destructive ? "destructive" : "normal"}
      data-variant={ghost ? "ghost" : outlined ? "outline" : invert ? "soft" : "solid"}
      data-size={size ?? "default"}
      className={cn("zeus-button", className)}
    >
      {prefix && <span className="zeus-button-icon">{prefix}</span>}
      {children}
      {suffix && <span className="zeus-button-icon">{suffix}</span>}
    </button>
  );
}

export function Card({ className, style, ...props }: ComponentProps<"div">) {
  return <div {...props} className={cn("zeus-card", className)} style={{
    background: "var(--component-card-background, var(--color-card))",
    borderImage: "var(--component-card-border-image)",
    boxShadow: "var(--component-card-box-shadow)",
    clipPath: "var(--component-card-clip-path)",
    ...style,
  }} />;
}

export function CardHeader({ className, ...props }: ComponentProps<"div">) {
  return <div {...props} className={cn("zeus-card-header", className)} />;
}

export function CardTitle({ className, ...props }: ComponentProps<"h3">) {
  return <h3 {...props} className={cn("zeus-card-title", className)} />;
}

export function CardDescription({ className, ...props }: ComponentProps<"p">) {
  return <p {...props} className={cn("text-sm text-muted-foreground leading-relaxed", className)} />;
}

export function CardContent({ className, ...props }: ComponentProps<"div">) {
  return <div {...props} className={cn("p-5", className)} />;
}

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input {...props} className={cn("zeus-input", className)} />;
}

interface BadgeProps extends Omit<ComponentProps<"span">, "color"> {
  tone?: "default" | "destructive" | "outline" | "secondary" | "success" | "warning";
}

export function Badge({ className, tone = "default", ...props }: BadgeProps) {
  return <span {...props} data-tone={tone} className={cn("zeus-badge", className)} />;
}
