import { Toaster as Sonner } from "sonner";

export function Toaster() {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-card group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:font-mono",
          description: "group-[.toast]:text-muted-foreground",
          error: "group-[.toaster]:text-destructive",
        },
      }}
    />
  );
}

export { toast } from "sonner";
