import { Toaster as Sonner } from "sonner";
import { useTheme } from "@/lib/theme";

export function ThemedToaster() {
  const { resolved } = useTheme();
  return (
    <Sonner
      theme={resolved}
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-popover group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:font-mono",
          description: "group-[.toast]:text-muted-foreground",
          error: "group-[.toaster]:text-destructive",
        },
      }}
    />
  );
}

export { toast } from "sonner";
