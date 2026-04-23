import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  CheckCircle2,
  Circle,
  Download,
  MessageSquare,
  Plug,
  Plus,
  Slack,
  Database as DatabaseIcon,
  CreditCard,
  Shield,
} from "lucide-react";
import biddedLogo from "@/assets/bidded-logo.png";
import { usePermissions } from "@/lib/auth";

type Member = {
  name: string;
  email: string;
  role: "Admin" | "Analyst" | "Viewer";
};

const members: Member[] = [
  { name: "Anna Lindgren", email: "anna@bidded.se", role: "Admin" },
  { name: "Erik Johansson", email: "erik@bidded.se", role: "Analyst" },
  { name: "Maja Svensson", email: "maja@bidded.se", role: "Analyst" },
  { name: "Oskar Berg", email: "oskar@bidded.se", role: "Viewer" },
];

const roleStyles: Record<Member["role"], string> = {
  Admin: "bg-primary/10 text-primary",
  Analyst: "bg-info/10 text-info",
  Viewer: "bg-muted text-muted-foreground",
};

type Integration = {
  name: string;
  description: string;
  icon: typeof Slack;
  connected: boolean;
};

const integrations: Integration[] = [
  { name: "Slack", description: "Post BID verdicts to #bids", icon: Slack, connected: true },
  { name: "Microsoft Teams", description: "Channel notifications", icon: MessageSquare, connected: false },
  { name: "TED EU", description: "European procurement feed", icon: DatabaseIcon, connected: true },
  { name: "Visma Opic", description: "Swedish procurement source", icon: DatabaseIcon, connected: true },
  { name: "Mercell", description: "Nordic tender platform", icon: DatabaseIcon, connected: false },
];

function initials(name: string) {
  return name.split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase();
}

function StatPill({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="font-mono text-base font-semibold tabular-nums text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

export default function Settings() {
  const permissions = usePermissions();

  if (!permissions.canManageTeam) {
    return (
      <>
        <PageHeader title="Settings" />
        <EmptyState
          icon={Shield}
          title="Admin access required"
          description="Workspace, billing, integrations, and team access are limited to admins."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader title="Settings" description="Configure workspace, team, integrations, models, and billing." />

      {/* Workspace header */}
      <Card className="mb-4 overflow-hidden">
        <div className="flex flex-col gap-4 bg-gradient-to-b from-secondary/40 to-transparent px-6 py-6 sm:flex-row sm:items-center sm:gap-6 sm:px-8">
          <img src={biddedLogo} alt="Bidded" className="h-16 w-auto sm:h-20" />
          <div className="flex-1 text-center sm:text-left">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Workspace</p>
            <p className="text-base font-semibold">Bidded · Demo Tenant</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              AI-powered bid/no-bid analysis for Swedish public procurement.
            </p>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 sm:justify-start">
              <StatPill value="5" label="procurements" />
              <span className="text-muted-foreground/40">·</span>
              <StatPill value="12" label="runs" />
              <span className="text-muted-foreground/40">·</span>
              <StatPill value="8" label="bids" />
              <span className="text-muted-foreground/40">·</span>
              <StatPill value="184" label="evidence items" />
            </div>
          </div>
        </div>
      </Card>

      {/* Team & Access */}
      <Card className="mb-4">
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm">Team &amp; Access</CardTitle>
          <Button size="sm" variant="outline">
            <Plus className="h-4 w-4" />
            Invite member
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y divide-border">
            {members.map((m) => (
              <li key={m.email} className="flex items-center gap-3 px-6 py-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 font-mono text-xs font-semibold text-primary">
                  {initials(m.name)}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">{m.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{m.email}</p>
                </div>
                <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${roleStyles[m.role]}`}>
                  {m.role}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Integrations */}
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle className="text-sm flex items-center gap-2"><Plug className="h-4 w-4" /> Integrations</CardTitle></CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border">
              {integrations.map((it) => {
                const Icon = it.icon;
                return (
                  <li key={it.name} className="flex items-center gap-3 px-6 py-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-md bg-muted text-foreground">
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{it.name}</p>
                      <p className="truncate text-xs text-muted-foreground">{it.description}</p>
                    </div>
                    {it.connected ? (
                      <span className="inline-flex items-center gap-1 rounded-md bg-success/10 px-2 py-0.5 text-xs font-medium text-success">
                        <CheckCircle2 className="h-3 w-3" /> Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                        <Circle className="h-3 w-3" /> Not connected
                      </span>
                    )}
                    <Button size="sm" variant={it.connected ? "outline" : "default"}>
                      {it.connected ? "Disconnect" : "Connect"}
                    </Button>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>

        {/* Notifications */}
        <Card>
          <CardHeader><CardTitle className="text-sm">Notifications</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {[
              { id: "n1", label: "Email on run complete", desc: "Get an email when an analysis finishes", on: true },
              { id: "n2", label: "Slack on BID verdict", desc: "Post to #bids when a BID is recommended", on: true },
              { id: "n3", label: "Weekly digest", desc: "Monday morning summary of last week", on: false },
              { id: "n4", label: "Deadline reminders", desc: "Notify 7 days before tender deadline", on: true },
            ].map((n) => (
              <div key={n.id} className="flex items-start justify-between gap-4 rounded-md border border-border/60 p-3">
                <div className="min-w-0">
                  <Label htmlFor={n.id} className="text-sm">{n.label}</Label>
                  <p className="mt-0.5 text-xs text-muted-foreground">{n.desc}</p>
                </div>
                <Switch id={n.id} defaultChecked={n.on} />
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Billing */}
        <Card>
          <CardHeader><CardTitle className="text-sm flex items-center gap-2"><CreditCard className="h-4 w-4" /> Billing</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold text-primary">
                Pro · 50 runs/mo
              </span>
              <Button size="sm" variant="outline">Manage billing</Button>
            </div>

            <div>
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-xs text-muted-foreground">Runs this month</span>
                <span className="font-mono text-xs tabular-nums text-foreground">34 / 50</span>
              </div>
              <Progress value={68} className="h-2" />
            </div>

            <div className="grid grid-cols-2 gap-3 border-t border-border/60 pt-3 text-sm">
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Next invoice</p>
                <p className="mt-0.5 font-medium text-foreground">May 1, 2026</p>
              </div>
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Amount due</p>
                <p className="mt-0.5 font-mono font-medium tabular-nums text-foreground">€499.00</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Model Configuration */}
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle className="text-sm">Model Configuration</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Model</Label>
                <Select defaultValue="claude-sonnet">
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="claude-sonnet">claude-3.7-sonnet</SelectItem>
                    <SelectItem value="claude-opus">claude-3-opus</SelectItem>
                    <SelectItem value="gpt-4o">gpt-4o</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Reasoning rounds <span className="font-mono text-xs text-muted-foreground">(2)</span></Label>
                <Input type="number" defaultValue={2} min={1} max={5} />
              </div>
              <div className="space-y-1.5">
                <Label>Temperature <span className="font-mono text-xs text-muted-foreground">(0.2)</span></Label>
                <Slider defaultValue={[20]} max={100} step={5} />
              </div>
              <div className="space-y-1.5">
                <Label>Top-p <span className="font-mono text-xs text-muted-foreground">(0.9)</span></Label>
                <Slider defaultValue={[90]} max={100} step={5} />
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <Label>Max tokens <span className="font-mono text-xs text-muted-foreground">(4096)</span></Label>
                <Slider defaultValue={[4096]} min={512} max={16384} step={512} />
              </div>
            </div>

            <div className="flex items-start justify-between gap-4 rounded-md border border-border/60 p-3">
              <div>
                <Label htmlFor="redteam" className="text-sm flex items-center gap-1.5"><Shield className="h-3.5 w-3.5" /> Enable Red Team agent</Label>
                <p className="mt-0.5 text-xs text-muted-foreground">Adversarial second pass to challenge each recommendation.</p>
              </div>
              <Switch id="redteam" defaultChecked />
            </div>

            <Button>Save Settings</Button>
          </CardContent>
        </Card>

        {/* API Keys */}
        <Card>
          <CardHeader><CardTitle className="text-sm">API Keys</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="anth">ANTHROPIC_API_KEY</Label>
              <Input id="anth" type="password" defaultValue="sk-ant-•••••••••••••••••••••••••" />
              <p className="text-[11px] text-muted-foreground">Last rotated · Mar 28, 2026</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="openai">OPENAI_API_KEY</Label>
              <Input id="openai" type="password" defaultValue="sk-•••••••••••••••••••••••••" />
              <p className="text-[11px] text-muted-foreground">Last rotated · Feb 12, 2026</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="surl">SUPABASE_URL</Label>
              <Input id="surl" defaultValue="https://••••••••.supabase.co" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="srole">SUPABASE_SERVICE_ROLE_KEY</Label>
              <Input id="srole" type="password" defaultValue="eyJhbGc•••••••••••••••••••••" />
              <p className="text-[11px] text-muted-foreground">Last rotated · Jan 04, 2026</p>
            </div>
            <Button>Save Settings</Button>
          </CardContent>
        </Card>

        {/* Storage */}
        <Card>
          <CardHeader><CardTitle className="text-sm">Storage</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label>Bucket</Label>
              <Input defaultValue="bidded-tenders" />
            </div>
            <div className="space-y-1.5">
              <Label>Region</Label>
              <Input defaultValue="eu-north-1" />
            </div>
            <div className="grid grid-cols-2 gap-3 rounded-md bg-muted/40 p-3 text-sm">
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Used</p>
                <p className="mt-0.5 font-mono font-medium tabular-nums text-foreground">4.2 GB</p>
              </div>
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Files</p>
                <p className="mt-0.5 font-mono font-medium tabular-nums text-foreground">312</p>
              </div>
            </div>
            <Button>Save Settings</Button>
          </CardContent>
        </Card>

        {/* Data & Retention */}
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle className="text-sm">Data &amp; Retention</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Document retention</Label>
                <Select defaultValue="365">
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="30">30 days</SelectItem>
                    <SelectItem value="90">90 days</SelectItem>
                    <SelectItem value="180">180 days</SelectItem>
                    <SelectItem value="365">365 days</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-start justify-between gap-4 rounded-md border border-border/60 p-3">
                <div>
                  <Label htmlFor="autodel" className="text-sm">Auto-delete failed runs</Label>
                  <p className="mt-0.5 text-xs text-muted-foreground">Remove failed runs after 7 days to save storage.</p>
                </div>
                <Switch id="autodel" defaultChecked />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline"><Download className="h-4 w-4" /> Export all data</Button>
              <Button variant="outline">Save Settings</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
