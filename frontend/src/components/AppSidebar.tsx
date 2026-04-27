import {
  LayoutDashboard,
  FileText,
  HandCoins,
  Building2,
  Settings,
} from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { usePermissions } from "@/lib/auth";
import { cn } from "@/lib/utils";

const items = [
  { title: "Dashboard", url: "/", icon: LayoutDashboard, end: true },
  { title: "Procurements", url: "/procurements", icon: FileText },
  { title: "Bids", url: "/bids", icon: HandCoins },
  { title: "Company Profile", url: "/company", icon: Building2 },
  { title: "Settings", url: "/settings", icon: Settings },
];

export function AppSidebar() {
  const { state } = useSidebar();
  const permissions = usePermissions();
  const collapsed = state === "collapsed";
  const location = useLocation();

  const isActive = (url: string, end?: boolean) =>
    end
      ? location.pathname === url
      : location.pathname === url || location.pathname.startsWith(url + "/");

  return (
    <Sidebar collapsible="icon" className="border-r border-sidebar-border">
      <SidebarContent className="bg-sidebar">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {items
                .filter((item) => item.url !== "/settings" || permissions.canManageTeam)
                .map((item) => {
                  const active = isActive(item.url, item.end);
                  return (
                    <SidebarMenuItem key={item.title}>
                      <SidebarMenuButton asChild isActive={active}>
                        <NavLink
                          to={item.url}
                          end={item.end}
                          className={cn(
                            "flex items-center gap-2 rounded-md text-sm",
                            active
                              ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                              : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                          )}
                        >
                          <item.icon className="h-4 w-4" />
                          {!collapsed && <span>{item.title}</span>}
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
