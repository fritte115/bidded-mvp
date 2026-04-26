import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  FileText,
  Gavel,
  HandCoins,
  Building2,
  Settings,
  ChevronRight,
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
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const items = [
  { title: "Procurements", url: "/procurements", icon: FileText },
  { title: "Bids", url: "/bids", icon: HandCoins },
  { title: "Company Profile", url: "/company", icon: Building2 },
  { title: "Settings", url: "/settings", icon: Settings },
];

const dashboardItems = [
  { title: "Overview", url: "/", end: true },
  { title: "Decisions", url: "/decisions" },
];

export function AppSidebar() {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const location = useLocation();

  const isActive = (url: string, end?: boolean) =>
    end ? location.pathname === url : location.pathname === url || location.pathname.startsWith(url + "/");
  const dashboardActive = isActive("/", true) || isActive("/decisions");
  const [dashboardOpen, setDashboardOpen] = useState(dashboardActive);

  useEffect(() => {
    if (dashboardActive) setDashboardOpen(true);
  }, [dashboardActive]);

  return (
    <Sidebar collapsible="icon" className="border-r border-sidebar-border">
      <SidebarContent className="bg-sidebar">
        <SidebarGroup>

          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <Collapsible open={dashboardOpen} onOpenChange={setDashboardOpen}>
                  <CollapsibleTrigger asChild>
                    <SidebarMenuButton
                      isActive={dashboardActive}
                      tooltip={collapsed ? "Dashboard" : undefined}
                      className={cn(
                        "flex items-center gap-2 rounded-md text-sm",
                        dashboardActive
                          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                          : "text-sidebar-foreground hover:bg-sidebar-accent/60",
                      )}
                    >
                      <LayoutDashboard className="h-4 w-4" />
                      {!collapsed && <span>Dashboard</span>}
                      {!collapsed && (
                        <ChevronRight
                          className={cn(
                            "ml-auto h-3.5 w-3.5 text-sidebar-foreground/60 transition-transform",
                            dashboardOpen && "rotate-90",
                          )}
                        />
                      )}
                    </SidebarMenuButton>
                  </CollapsibleTrigger>
                  {!collapsed && (
                    <CollapsibleContent>
                      <SidebarMenuSub>
                        {dashboardItems.map((item) => {
                          const active = isActive(item.url, item.end);
                          return (
                            <SidebarMenuSubItem key={item.title}>
                              <SidebarMenuSubButton asChild isActive={active} size="sm">
                                <NavLink to={item.url} end={item.end}>
                                  {item.title === "Decisions" && <Gavel className="h-3.5 w-3.5" />}
                                  <span>{item.title}</span>
                                </NavLink>
                              </SidebarMenuSubButton>
                            </SidebarMenuSubItem>
                          );
                        })}
                      </SidebarMenuSub>
                    </CollapsibleContent>
                  )}
                </Collapsible>
              </SidebarMenuItem>
              {items.map((item) => {
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
