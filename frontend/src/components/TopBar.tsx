import { Bell, LogOut } from "lucide-react";
import { useLocation, Link } from "react-router-dom";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth";
import biddedMark from "@/assets/bidded-mark.png";

const titles: { match: (p: string) => boolean; title: string }[] = [
  { match: (p) => p === "/", title: "Dashboard" },
  { match: (p) => p === "/procurements", title: "Procurements" },
  { match: (p) => p === "/procurements/new", title: "Register Procurement" },
  { match: (p) => /^\/runs\/[^/]+\/evidence$/.test(p), title: "Evidence Board" },
  { match: (p) => /^\/runs\/[^/]+$/.test(p), title: "Run Detail" },
  { match: (p) => p === "/decisions", title: "Bid Decisions" },
  { match: (p) => /^\/decisions\/[^/]+$/.test(p), title: "Decision Detail" },
  { match: (p) => p === "/bids", title: "Bids" },
  { match: (p) => p === "/bids/new", title: "New Bid" },
  { match: (p) => /^\/bids\/[^/]+\/edit$/.test(p), title: "Edit Bid" },
  { match: (p) => /^\/drafts\/[^/]+$/.test(p), title: "Draft Anbud" },
  { match: (p) => p === "/company", title: "Company Profile" },
  { match: (p) => p === "/settings", title: "Settings" },
];

export function TopBar() {
  const { pathname } = useLocation();
  const { displayName, organizationName, role, signOut, user } = useAuth();
  const title = titles.find((t) => t.match(pathname))?.title ?? "Bidded";
  const label = displayName ?? user?.email ?? "User";
  const initials = label
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur">
      <div className="flex items-center gap-3">
        <SidebarTrigger className="text-muted-foreground hover:text-foreground" />
        <div className="h-4 w-px bg-border" />
        <Link to="/" className="flex items-center gap-2">
          <img src={biddedMark} alt="Bidded" className="h-6 w-6 shrink-0 object-contain" />
          <span className="text-base font-semibold text-foreground">Bidded</span>
        </Link>
        <div className="h-4 w-px bg-border" />
        <span className="text-sm text-muted-foreground">{title}</span>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
          <Bell className="h-4 w-4" />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-primary/10 text-xs font-semibold text-primary"
            >
              {initials || "U"}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64">
            <DropdownMenuLabel>
              <span className="block truncate text-sm">{label}</span>
              <span className="block truncate text-xs font-normal text-muted-foreground">
                {organizationName ?? "No organization"} · {role ?? "no role"}
              </span>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void signOut()}>
              <LogOut className="h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
